from typing import List, Optional
from pydantic import BaseModel

class ProjectCard(BaseModel):
    id: str
    name: str
    description: str
    status: str = "active"
    url: Optional[str] = None

PROJECTS = [
    ProjectCard(
        id="grademy",
        name="GradeMy / Shelf Report",
        description="Automated grading and shelf reporting for libraries.",
    ),
    ProjectCard(
        id="warden",
        name="Warden / McHarness",
        description="Supervised agent control room and local-first engine.",
    ),
    ProjectCard(
        id="roadscout",
        name="RoadScout",
        description="Intelligent road condition monitoring and reporting.",
    ),
    ProjectCard(
        id="foreman",
        name="Marius Foreman",
        description="Fleet management and task orchestration for Marius agents.",
    ),
    ProjectCard(
        id="gsv",
        name="GoodStuffVault",
        description="Curated collection of high-quality digital assets.",
    ),
    ProjectCard(
        id="hybrid",
        name="Marius Core / Hybrid",
        description="Resident personal AI assistant and core engine.",
    ),
]

def get_projects() -> List[ProjectCard]:
    return PROJECTS
