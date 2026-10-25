"""Idempotent seed of portfolio-owned content, then the one-off all_projects import.

Skips a row when a natural key already exists. Media/images are not seeded.
The import (app/api/routes/project/project_import.py) copies the retired
all_projects app's projects, skills and images in once; it never raises.
Run: python bootstrap.py
Also runs on API startup.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.portfolio.education.model import Education
from app.api.routes.portfolio.profile.model import ProfileInfo
from app.api.routes.portfolio.social_media.model import SocialMediaLink
from app.api.routes.portfolio.work_experience.model import WorkExperience
from app.api.routes.project.project_import import import_all_projects
from app.config import db_settings, project_settings
from app.db.garage_session import GarageSession
from app.db.postgress_session import PostgresSession

logger = logging.getLogger(__name__)

PROFILE = {
    "name": "Karan Parmar",
    "headline": "AI & ML Engineer: Engineering Next-Gen software.",
    "hero_greeting": "Hi, my name is",
    "about": (
        "AI/ML Engineer who builds and deploys scalable applications using Python, "
        "FastAPI/Django/Flask, and cloud platforms like AWS. My expertise centers on "
        "Deep Learning and LLM integration (Llama, OpenAI, Mistral), where I have "
        "hands-on experience fine-tuning models and integrating APIs like Gemini into "
        "production systems. I'm passionate about delivering production-ready solutions; "
        "in my experience, I have improved system efficiency by 1.5x and reduced costs "
        "by 7% through scalable backend automation, and I consistently automate "
        "AWS/DigitalOcean deployment pipelines using Docker and CI/CD. I am focused on "
        "leveraging data-driven insights to develop features and tackle complex problems, "
        "such as building machine learning models for credit card fraud detection and "
        "leading full-stack projects that significantly boost feature engagement."
    ),
    "email": "karan.ai.engineer@gmail.com",
    "phone": "+918793759908",
    "location": "Mumbai",
    "available_for_work": False,
}

EDUCATION = [
    {
        "sequence": 1,
        "school": "Universal College of Engineering",
        "degree": "Bachelors",
        "field_of_study": "Artificial Intelligence and Machine Learning ",
        "start_year": 2021,
        "end_year": 2025,
        "score": Decimal("7.97"),
        "score_label": "GPA",
        "description": (
            "Completed a focused Bachelor of Engineering program in Artificial "
            "Intelligence and Machine Learning, with an Honours specialization in Data "
            "Science. The curriculum provided a robust foundation in machine learning "
            "algorithms, deep learning, and advanced data manipulation. I leveraged this "
            "academic grounding to specialize in building and deploying production-ready "
            "AI/ML systems, bridging the gap between theoretical models and scalable, "
            "real-world applications using technologies like Flask, FastAPI, and cloud "
            "platforms."
        ),
    },
    {
        "sequence": 2,
        "school": "R.P Jr. College",
        "degree": "High Secondary Education (Science)",
        "field_of_study": None,
        "start_year": 2019,
        "end_year": 2021,
        "score": Decimal("84.00"),
        "score_label": "%",
        "description": (
            "Navigated my final years of secondary education facing significant resource "
            "limitations and the impact of the COVID-19 pandemic on traditional learning. "
            "Despite these obstacles, I leveraged my strong aptitude for theory and "
            "quantitative subjects to excel in written examinations. Demonstrated high "
            "self-motivation and resourcefulness to prepare for competitive entrance "
            "examinations, ultimately securing admission."
        ),
    },
    {
        "sequence": 3,
        "school": "St Aloysius High School",
        "degree": "Secondary School",
        "field_of_study": None,
        "start_year": 2009,
        "end_year": 2019,
        "score": Decimal("68.00"),
        "score_label": "%",
        "description": (
            "This is where I learned how, to connect to people, how to make friends, "
            "how thing work in the world, slowly discovered my interact in science and "
            "math. Enjoyed Life. "
        ),
    },
]

WORK = [
    {
        "sequence": 1,
        "company": "Quralyst",
        "company_url": "https://www.quralyst.ai/",
        "position": "Software Engineer",
        "location": "US (Remote)",
        "employment_type": "Full time",
        "description": [
            "Architected and optimized a multi-provider AI orchestration pipeline, enabling dynamic switching between LLM vendors to maximize cost-efficiency and user choice.",
            "Designed and scaled a high-throughput backend capable of handling long-running asynchronous tasks, successfully minimizing latency while maintaining high data accuracy.",
            "Engineered robust database schemas and state-management systems to support complex, multi-stage AI workflows and high-concurrency operations.",
            "Collaborated across cross-functional teams to take features from initial concept through rigorous testing to production deployment, ensuring seamless UI/UX and backend integration.",
        ],
        "start_date": date(2026, 3, 11),
        "end_date": None,
    },
    {
        "sequence": 2,
        "company": "Callify.ai",
        "company_url": "https://callify.ai/",
        "position": "AI Engineer",
        "location": "Mumbai",
        "employment_type": "Full time",
        "description": [
            "Analyzing data to derive actionable insights.",
            "Building scalable backends with FastAPI.",
            "Working with LLMs (OpenAI and others).",
            "Enhancing user experience through Speech-to-Text (STT) and Text-to-Speech (TTS) systems.",
            "Deploying AI solutions efficiently on the cloud.",
        ],
        "start_date": date(2025, 8, 7),
        "end_date": date(2026, 2, 15),
    },
    {
        "sequence": 3,
        "company": "Chien Technologies Pvt Ltd",
        "company_url": "https://in.linkedin.com/company/chientech",
        "position": "Software Developer intern",
        "location": "Mumbai",
        "employment_type": "Internship",
        "description": [
            "Developing Scalable software using python and Machine Learning Techniques.",
            "Leveraging Image-Recognition models like Yolo to build Real time Scanning Application.",
            "Web Scraping data and preprocessing it for preparing high quality dataset for training models.",
            "Using LLMs like OpenAi and Llama 3 to remove the error of NLP.",
            "Creating backend Api with the help of Flask and Node Js",
            "Integration Various Services like Email and Whatsapp for seamless user experience",
            "Deploying entire systems on cloud like AWS & Digital Ocean using Docker and creating CI/CD pipeline for automating the whole deploying process.",
        ],
        "start_date": date(2025, 1, 10),
        "end_date": date(2025, 7, 11),
    },
    {
        "sequence": 4,
        "company": "HireIntel",
        "company_url": "https://hireintel.app/",
        "position": "Python Developer",
        "location": "Bangalore (Remote)",
        "employment_type": "Internship",
        "description": [
            "Lead a team of Python developers in full-stack web development, managing both frontend and backend tasks",
            "Integrated advanced APIs such as OpenAI and Gemini into existing applications, improving functionality which resulted in more than double the user engagement on key features implemented across projects.",
            "Oversaw project deployment, version control using Git, and implemented vector-based data models for recommendation systems",
            "Additionally, handled data preprocessing and analysis, and created prompts for precise LLM model responses.",
        ],
        "start_date": date(2024, 8, 1),
        "end_date": date(2024, 9, 30),
    },
    {
        "sequence": 5,
        "company": "Branding Catalyst Pvt Ltd.",
        "company_url": "https://www.brandingcatalyst.in/",
        "position": "Artificial Intelligence and Machine Learning Intern",
        "location": "Mumbai",
        "employment_type": "Internship",
        "description": [
            "Collaborated closely with other departments as part of the most junior member on the team; contributed ideas that helped streamline communication processes among teams during full-stack project phases.",
            "Developed backend systems using Flask and Django, integrating seamlessly with frontend components",
            "Integrated APIs like OpenAI and Gemini, fine-tuned and deployed LLMs such as Llama 2, Mistral, and Open Orca",
            "Designed systems in collaboration with clients and conducted data preprocessing to optimize model performance.",
        ],
        "start_date": date(2024, 1, 1),
        "end_date": date(2024, 3, 31),
    },
    {
        "sequence": 6,
        "company": "InternConnect ",
        "company_url": None,
        "position": "Web Developer Internship",
        "location": "Mumbai",
        "employment_type": "Internship",
        "description": [
            "Designed and developed user-friendly frontends for client websites.",
            "managed client interactions to meet specific needs",
            "handled full-stack development by integrating frontend and backend functionalities for complete web solutions",
        ],
        "start_date": date(2023, 8, 1),
        "end_date": date(2023, 9, 30),
    },
    {
        "sequence": 7,
        "company": "Tradingseva2020 ",
        "company_url": None,
        "position": "Graphic Designer",
        "location": "Mumbai",
        "employment_type": "Part time",
        "description": [
            "Designed and executed visually stunning print and digital media graphics, including logos, website banners, and promotional materials, resulting in a 40% increase in customer engagement and a 25% boost in brand recognition.",
            "Developed and maintained visually appealing company websites, produced and edited YouTube videos, and managed ad campaigns to drive brand awareness",
            "Engaged with clients to understand their needs, leading to successful lead conversions and long-term partnerships.",
        ],
        "start_date": date(2022, 2, 3),
        "end_date": date(2022, 8, 3),
    },
]

SOCIAL = [
    {
        "platform": "linkedin",
        "label": "linkedin",
        "url": "https://www.linkedin.com/in/karan-parmar-715ab7225/",
        "sequence": 1,
        "show_in_rail": True,
    },
    {
        "platform": "github",
        "label": "github",
        "url": "https://github.com/Karan-parmar-007",
        "sequence": 2,
        "show_in_rail": True,
    },
    {
        "platform": "instagram",
        "label": "instagram",
        "url": "https://www.instagram.com/vibecodewithk/",
        "sequence": 3,
        "show_in_rail": False,
    },
    {
        "platform": "youtube",
        "label": "youtube",
        "url": "https://www.youtube.com/@VibeCodeWithK",
        "sequence": 4,
        "show_in_rail": True,
    },
    {
        "platform": "twitter",
        "label": "X",
        "url": "https://x.com/VibeCodeWithK",
        "sequence": 5,
        "show_in_rail": False,
    },
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _one(session: AsyncSession, stmt):
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def seed(session: AsyncSession) -> None:
    now = _now()

    existing_profile = await _one(session, select(ProfileInfo).limit(1))
    if existing_profile:
        print(f"profile exists ({existing_profile.email}) — skip")
    else:
        session.add(
            ProfileInfo(
                **PROFILE,
                resume_media_id=None,
                profile_image_media_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        print(f"profile added ({PROFILE['email']})")

    for row in EDUCATION:
        found = await _one(
            session,
            select(Education).where(
                Education.school == row["school"],
                Education.degree == row["degree"],
                Education.start_year == row["start_year"],
            ),
        )
        if found:
            print(f"education exists ({row['school']}) — skip")
            continue
        session.add(Education(**row, created_at=now, updated_at=now))
        print(f"education added ({row['school']})")

    for row in WORK:
        found = await _one(
            session,
            select(WorkExperience).where(
                WorkExperience.company == row["company"],
                WorkExperience.position == row["position"],
                WorkExperience.start_date == row["start_date"],
            ),
        )
        if found:
            print(f"work exists ({row['company'].strip()} / {row['position']}) — skip")
            continue
        session.add(WorkExperience(**row, created_at=now, updated_at=now))
        print(f"work added ({row['company'].strip()} / {row['position']})")

    for row in SOCIAL:
        found = await _one(
            session, select(SocialMediaLink).where(SocialMediaLink.url == row["url"])
        )
        if found:
            print(f"social exists ({row['platform']}) — skip")
            continue
        session.add(SocialMediaLink(**row, created_at=now, updated_at=now))
        print(f"social added ({row['platform']})")


async def import_legacy_projects(sessionmaker, garage_session: GarageSession) -> None:
    bucket = project_settings.ALL_PROJECTS_GARAGE_BUCKET_NAME or db_settings.GARAGE_BUCKET_NAME
    try:
        async with sessionmaker() as session:
            async for garage in garage_session.get_client():
                await import_all_projects(
                    session,
                    garage,
                    source_bucket=bucket,
                    studio_url=project_settings.studio_url,
                )
    except Exception:
        # e.g. Garage unreachable while opening the client; retried next start.
        logger.exception("all_projects import skipped")


async def run_bootstrap(sessionmaker, garage_session: GarageSession | None = None) -> None:
    async with sessionmaker() as session:
        await seed(session)
        await session.commit()
        print("Portfolio bootstrap complete")
    if garage_session is not None:
        await import_legacy_projects(sessionmaker, garage_session)


async def main() -> None:
    postgres = PostgresSession()
    await postgres.verify_connection()
    await run_bootstrap(postgres._sessionmaker, GarageSession())
    await postgres.dispose()


if __name__ == "__main__":
    asyncio.run(main())
