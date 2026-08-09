from app.models import Job


def metadata_for_language(job: Job, language: str) -> tuple[str, str]:
    """Return the effective title/description for a publish language."""
    if language == "en":
        title = (
            job.final_title_en
            or job.final_title
            or job.suggested_title_en
            or job.suggested_title_fi
            or "Video"
        )
        description = (
            job.final_description_en
            or job.final_description
            or job.suggested_description_en
            or job.suggested_description_fi
            or ""
        )
    else:
        title = (
            job.final_title_fi
            or job.final_title
            or job.suggested_title_fi
            or job.suggested_title_en
            or "Video"
        )
        description = (
            job.final_description_fi
            or job.final_description
            or job.suggested_description_fi
            or job.suggested_description_en
            or ""
        )
    return title, description


def editable_metadata_payload(job: Job) -> dict:
    return {
        "title_fi": job.final_title_fi or job.final_title or job.suggested_title_fi or "",
        "title_en": job.final_title_en or job.final_title or job.suggested_title_en or "",
        "description_fi": (
            job.final_description_fi
            or job.final_description
            or job.suggested_description_fi
            or ""
        ),
        "description_en": (
            job.final_description_en
            or job.final_description
            or job.suggested_description_en
            or ""
        ),
        "final_title_fi": job.final_title_fi or "",
        "final_title_en": job.final_title_en or "",
        "final_description_fi": job.final_description_fi or "",
        "final_description_en": job.final_description_en or "",
        "final_title": job.final_title or "",
        "final_description": job.final_description or "",
    }


def set_metadata(job: Job, language: str, title: str | None, description: str | None):
    clean_title = title.strip()[:255] if isinstance(title, str) else None
    clean_description = description.strip() if isinstance(description, str) else None
    if language == "en":
        if title is not None:
            job.final_title_en = clean_title or None
        if description is not None:
            job.final_description_en = clean_description or None
    else:
        if title is not None:
            job.final_title_fi = clean_title or None
        if description is not None:
            job.final_description_fi = clean_description or None
