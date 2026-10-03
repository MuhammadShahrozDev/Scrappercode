import os
from pathlib import Path

import mysql.connector
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
INPUT_FILE = BASE_DIR / "jobs" / "jobs_combined.xlsx"


def clean_value(value):
    if pd.isna(value):
        return None

    if isinstance(value, str):
        value = value.strip()
        return value if value else None

    return value


def get_connection():
    required = [
        "DB_HOST",
        "DB_NAME",
        "DB_USER",
        "DB_PASSWORD",
    ]

    missing = [name for name in required if not os.getenv(name)]

    if missing:
        raise RuntimeError(
            f"Missing database environment variables: {', '.join(missing)}"
        )

    return mysql.connector.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT", "3306")),
        database=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        charset="utf8mb4",
    )


def main():
    if not INPUT_FILE.exists():
        raise FileNotFoundError(
            f"Final jobs file not found: {INPUT_FILE}"
        )

    df = pd.read_excel(INPUT_FILE)

    print(f"Loaded {len(df)} jobs for MySQL.")

    connection = get_connection()
    cursor = connection.cursor()

    query = """
        INSERT INTO scraped_jobs (
            source,
            job_title,
            job_description,
            role,
            company_name,
            company_website,
            company_linkedin,
            hiring_contact,
            person_1_name,
            person_1_role,
            person_1_profile_url,
            person_2_name,
            person_2_role,
            person_2_profile_url,
            job_url
        )
        VALUES (
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s
        )
        ON DUPLICATE KEY UPDATE
            source = VALUES(source),
            job_title = VALUES(job_title),
            job_description = VALUES(job_description),
            role = VALUES(role),
            company_name = VALUES(company_name),
            company_website = VALUES(company_website),
            company_linkedin = VALUES(company_linkedin),
            hiring_contact = VALUES(hiring_contact),
            person_1_name = VALUES(person_1_name),
            person_1_role = VALUES(person_1_role),
            person_1_profile_url = VALUES(person_1_profile_url),
            person_2_name = VALUES(person_2_name),
            person_2_role = VALUES(person_2_role),
            person_2_profile_url = VALUES(person_2_profile_url),
            updated_at = CURRENT_TIMESTAMP
    """

    processed = 0
    skipped = 0

    try:
        for _, row in df.iterrows():

            job_url = clean_value(row.get("job_url"))

            if not job_url:
                skipped += 1

                print(
                    f"[SKIP] Missing job_url: "
                    f"{clean_value(row.get('company_name'))} - "
                    f"{clean_value(row.get('job_title'))}"
                )

                continue

            values = (
                clean_value(row.get("source")),
                clean_value(row.get("job_title")),
                clean_value(row.get("job_description")),
                clean_value(row.get("role")),
                clean_value(row.get("company_name")),
                clean_value(row.get("company_website")),
                clean_value(row.get("company_linkedin")),
                clean_value(row.get("hiring_contact")),
                clean_value(row.get("person_1_name")),
                clean_value(row.get("person_1_role")),
                clean_value(row.get("person_1_profile_url")),
                clean_value(row.get("person_2_name")),
                clean_value(row.get("person_2_role")),
                clean_value(row.get("person_2_profile_url")),
                job_url,
            )

            cursor.execute(query, values)
            processed += 1

        connection.commit()

        print("=" * 60)
        print("MySQL sync completed successfully.")
        print(f"Processed: {processed}")
        print(f"Skipped:   {skipped}")
        print("=" * 60)

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()