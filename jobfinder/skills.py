import re
from collections import Counter

import pandas as pd

# canonical name -> regex (word-boundary aware; handles c++, c#, .net, node.js)
SKILLS = {
    "Python": r"python", "Java": r"java(?!\s*script)", "JavaScript": r"javascript|\bjs\b|ecmascript",
    "TypeScript": r"typescript", "C++": r"c\+\+", "C#": r"c#", "Go": r"\bgolang\b|\bgo\s+(?:lang|developer|programming)",
    "Kotlin": r"kotlin", "Swift": r"\bswift\b", "PHP": r"\bphp\b", "Ruby": r"\bruby\b",
    "React": r"react(?:\.?js)?\b", "Angular": r"angular", "Vue": r"\bvue(?:\.?js)?\b", "Next.js": r"next\.?js",
    "Node.js": r"node(?:\.?js)?\b", "Express": r"express\.?js|(?:node\w*|nest\w*)\s*[/,&(]\s*express\b|\bexpress\s+(?:framework|server|api|app)", "Django": r"django", "Flask": r"flask",
    "FastAPI": r"fastapi", "Spring Boot": r"spring\s*(?:boot|framework|mvc|cloud|security|data)|(?:java|hibernate)\s*[/,&(]\s*spring\b|\bspring\s*[/,]\s*hibernate", ".NET": r"\.net\b|asp\.net",
    "HTML/CSS": r"\bhtml5?\b|\bcss3?\b", "Tailwind": r"tailwind", "Redux": r"redux",
    "SQL": r"\bsql\b|mysql|postgres(?:ql)?|oracle db|mssql", "PostgreSQL": r"postgres",
    "MongoDB": r"mongo(?:db)?", "Redis": r"redis", "Kafka": r"kafka", "Elasticsearch": r"elasticsearch|opensearch",
    "AWS": r"\baws\b|amazon web services", "Azure": r"azure", "GCP": r"\bgcp\b|google cloud",
    "Docker": r"docker", "Kubernetes": r"kubernetes|\bk8s\b", "Terraform": r"terraform",
    "CI/CD": r"ci/cd|\bci\b.{0,3}\bcd\b|jenkins|github actions|gitlab ci", "Linux": r"linux|unix",
    "Git": r"\bgit\b|github|gitlab|bitbucket", "REST APIs": r"restful|rest\s*apis?|rest\s*(?:web\s*)?services?|\brest\s*/\s*soap",
    "GraphQL": r"graphql", "Microservices": r"microservices?", "System Design": r"system design|low.level design|hld|lld",
    "DSA": r"data structures?|algorithms?|\bdsa\b", "OOP": r"\boop\b|object.oriented",
    "Machine Learning": r"machine learning|\bml\b|deep learning|\bnlp\b", "Pandas/NumPy": r"pandas|numpy",
    "Spark": r"\bspark\b|pyspark", "Airflow": r"airflow", "Selenium": r"selenium", "Testing": r"unit tests?|unit testing|integration tests?|\bjest\b|pytest|junit|\btdd\b|test automation|test.driven",
    "Agile": r"agile|scrum", "Android": r"android", "iOS": r"\bios\b", "React Native": r"react native",
    "Flutter": r"flutter", "LLM/GenAI": r"\bllm\b|generative ai|genai|openai|langchain",
}
_COMPILED = {k: re.compile(v, re.I) for k, v in SKILLS.items()}


def extract(text: str) -> set[str]:
    text = text or ""
    return {k for k, rx in _COMPILED.items() if rx.search(text)}


def add_skills(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    blob = df["title"].fillna("") + " \n " + df["description"].fillna("")
    df["skills"] = blob.map(lambda t: sorted(extract(t)))
    return df


def demand(df: pd.DataFrame) -> pd.DataFrame:
    """Skill -> job count and share of jobs. Only jobs that have a description are counted."""
    d = df[df["description"].fillna("").str.len() > 50] if "description" in df else df
    if "skills" not in d:
        d = add_skills(d)
    counts = Counter(s for row in d["skills"] for s in row)
    out = pd.DataFrame(counts.most_common(), columns=["skill", "jobs"])
    out["share_%"] = (out["jobs"] / max(len(d), 1) * 100).round(1)
    return out


def pdf_text(file) -> str:
    from pypdf import PdfReader
    from .experience import normalize
    return normalize("\n".join((p.extract_text() or "") for p in PdfReader(file).pages[:25]))


def add_match(df: pd.DataFrame, mine: list[str], years: float | None = None) -> pd.DataFrame:
    """match_% = share of a job's detected skills you have (floor of 5 so 1-skill postings can't hit 100%);
    missing = skills you lack; exp_ok = the posting's minimum experience is within reach."""
    df = df.copy()
    have = set(mine)
    df["missing"] = df["skills"].map(lambda s: [x for x in s if x not in have])
    df["match_%"] = df["skills"].map(lambda s: round(100 * len(have & set(s)) / max(len(s), 5)) if s else None)
    if years is not None:
        df["exp_ok"] = df["exp_min"].map(lambda m: m is None or pd.isna(m) or m <= years + 1)
    return df


def gaps(df: pd.DataFrame, mine: list[str]) -> pd.DataFrame:
    """Skills in demand that you lack, ranked by share of jobs."""
    d = demand(df)
    return d[~d["skill"].isin(mine)].reset_index(drop=True)
