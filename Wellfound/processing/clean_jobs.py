import json
from pathlib import Path
from datetime import datetime

# Project root (this file now lives one level down, in
# scraping/ or processing/), so go up an extra level.
BASE_DIR = Path(__file__).resolve().parent.parent

INPUT_DIR = BASE_DIR / "jobs"
OUTPUT_PREFIX = "jobs_"


def extract_contact(job):
    startup = job.get("startup", {})

    # -------------------------
    # Extract founders
    # -------------------------
    founders = []

    for founder in startup.get("currentFounderRoles", []):
        user = founder.get("user", {})

        if user.get("name"):
            founders.append(user["name"])


    # -------------------------
    # Extract hiring manager
    # -------------------------
    hiring_manager = None

    recruiting_contact = job.get("recruitingContact")

    if recruiting_contact:
        user = recruiting_contact.get("user", {})

        if user.get("name"):
            hiring_manager = user["name"]


    # -------------------------
    # Choose primary contact
    # -------------------------
    hiring_contact = (
        hiring_manager
        if hiring_manager
        else (founders[0] if founders else None)
    )


    return {
        "founders": founders,
        "hiring_manager": hiring_manager,
        "hiring_contact": hiring_contact
    }


def extract_job(job):

    startup = job.get("startup", {})
    remote_config = job.get("remoteConfig") or {}


    skills = [
        skill.get("displayName")
        for skill in job.get("skills", [])
        if skill.get("displayName")
    ]


    return {
        "id": job.get("id"),
        "source": "wellfound",

        "title": job.get("title"),
        "role": job.get("primaryRoleTitle"),

        "company_id": startup.get("id"),
        "company_name": startup.get("name"),
        "company_slug": startup.get("slug"),
        "company_location": [
            tag.get("name") or tag.get("displayName")
            for tag in startup.get("locationTaggings", [])
            if tag.get("name") or tag.get("displayName")
        ],
        "company_size": startup.get("companySize"),

        "description": job.get("description"),

        "location": job.get("locationNames", []),

        "remote": job.get("remote"),
        "remote_type": remote_config.get("kind"),

        "relocation_allowed": job.get("allowRelocation"),

        "job_type": job.get("jobType"),

        "experience_min": job.get("yearsExperienceMin"),
        "experience_max": job.get("yearsExperienceMax"),

        "skills": skills,

        "compensation": job.get("compensation"),
        "equity": job.get("equity"),

        "posted_timestamp": job.get("liveStartAt"),

        "visa_sponsorship": job.get("visaSponsorship"),

        "url": job.get("url"),

        "contact": extract_contact(job),

        "metadata": {
            "scraped_at": datetime.utcnow().isoformat()
        }
    }



def process_file(input_file):

    output_file = (
        INPUT_DIR /
        f"{OUTPUT_PREFIX}{input_file.stem}.json"
    )

    cleaned_jobs = []


    with open(input_file, "r", encoding="utf-8") as f:

        for line_number, line in enumerate(f, start=1):

            line = line.strip()

            if not line:
                continue


            try:
                job = json.loads(line)
                cleaned_jobs.append(
                    extract_job(job)
                )

            except json.JSONDecodeError:
                print(
                    f"Skipping invalid JSON "
                    f"{input_file.name} line {line_number}"
                )


    with open(output_file, "w", encoding="utf-8") as f:

        json.dump(
            cleaned_jobs,
            f,
            indent=2,
            ensure_ascii=False
        )


    print(
        f"{input_file.name} -> "
        f"{output_file.name} "
        f"({len(cleaned_jobs)} jobs)"
    )



def main():

    for file in INPUT_DIR.glob("*.jsonl"):

        process_file(file)



if __name__ == "__main__":
    main()