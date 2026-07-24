import json
from pathlib import Path

from pipeline.skills import extract_opportunity_skills

LEXICON_PATH = Path(__file__).resolve().parents[1] / "pipeline" / "skills_lexicon.json"
LEXICON_NAMES = {
    skill["name"] for skill in json.loads(LEXICON_PATH.read_text(encoding="utf-8"))["skills"]
}
SOFT_GENERIC_SKILLS = {
    "Communication",
    "Leadership",
    "Teamwork",
    "Problem Solving",
    "Time Management",
    "Adaptability",
    "Customer Service",
    "Data Entry",
    "Microsoft Office",
    "Critical Thinking",
}


def test_forward_deployed_engineer_combines_explicit_and_role_implied_skills():
    skills = extract_opportunity_skills(
        "Forward Deployed Engineer, New Grad",
        "Build production workflows with Python and write SQL for operational datasets.",
    )

    assert "Python" in skills
    assert "SQL" in skills
    assert "Data Analysis" in skills
    assert skills.index("Python") < skills.index("Data Analysis")
    assert skills.index("SQL") < skills.index("Data Analysis")


def test_frontend_engineer_includes_frontend_stack_from_role_and_description():
    skills = extract_opportunity_skills(
        "Frontend Engineer Intern",
        "Build user interfaces with React and TypeScript across our student product.",
    )

    assert "React" in skills
    assert "JavaScript" in skills
    assert "TypeScript" in skills
    assert "HTML" in skills
    assert "CSS" in skills


def test_role_phrase_with_no_explicit_skills_still_returns_implied_skills():
    skills = extract_opportunity_skills(
        "Backend Engineer",
        "Join a rotational program for students and work with product teams.",
    )

    assert "REST APIs" in skills
    assert "SQL" in skills
    assert "PostgreSQL" in skills
    assert "Docker" in skills


def test_company_name_guard_removes_company_aliases_from_haystack():
    skills = extract_opportunity_skills(
        "Account Executive",
        "GitLab is looking for a seller who can help customers adopt GitLab.",
        company_name="GitLab",
    )

    assert "Git" not in skills


def test_soft_generic_skills_do_not_match_from_prose():
    skills = extract_opportunity_skills(
        "Program Associate",
        "Strong communication skills, leadership, teamwork, problem solving, "
        "time management, adaptability, customer service, data entry, "
        "Microsoft Office, and critical thinking are valued.",
    )

    assert SOFT_GENERIC_SKILLS.isdisjoint(skills)


def test_soft_generic_skills_can_still_come_from_role_map():
    skills = extract_opportunity_skills(
        "Strategy Consultant",
        "Join client project teams and help structure ambiguous business problems.",
    )

    assert "Communication" in skills
    assert "Problem Solving" in skills


def test_ambiguous_bare_aliases_are_ignored_for_opportunities():
    skills = extract_opportunity_skills(
        "Generalist Intern",
        "This role includes compliance tasks, design reviews, research planning, "
        "spring hiring support, and notion documentation.",
    )

    assert "Regulatory Compliance" not in skills
    assert "UI/UX Design" not in skills
    assert "Research" not in skills
    assert "Spring Boot" not in skills
    assert "Notion" not in skills


def test_non_ambiguous_aliases_for_stoplisted_skills_still_match():
    skills = extract_opportunity_skills(
        "Software Engineer",
        "Build Spring Boot services, perform regulatory compliance work, "
        "run literature review, and partner with ux design teams.",
    )

    assert "Spring Boot" in skills
    assert "Regulatory Compliance" in skills
    assert "Research" in skills
    assert "UI/UX Design" in skills


def test_result_is_capped_deduped_and_canonical():
    skills = extract_opportunity_skills(
        "Frontend Backend Data Scientist Machine Learning DevOps Product Manager",
        "Python python JavaScript TypeScript Java SQL HTML CSS React React.js "
        "Node.js Django Flask FastAPI PostgreSQL Docker Kubernetes AWS Linux "
        "TensorFlow PyTorch Excel Figma SEO",
    )

    assert len(skills) == 12
    assert len({skill.lower() for skill in skills}) == len(skills)
    assert all(skill in LEXICON_NAMES for skill in skills)
