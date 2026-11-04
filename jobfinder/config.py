import re

CITIES = ["Bangalore", "Mumbai", "Pune"]
SITES = ["indeed", "linkedin", "naukri", "google"]

# Wide net: many roles/stacks, filtered locally afterwards.
QUERIES = [
    "software engineer fresher", "software developer", "SDE 1", "junior developer",
    "graduate engineer trainee", "full stack developer", "frontend developer",
    "backend developer", "python developer", "java developer", "react developer",
    "node.js developer", "data engineer", "devops engineer", "QA automation engineer",
    "android developer", "ios developer", ".net developer",
]

SENIOR = ("senior", "sr.", "sr ", "lead", "principal", "staff", "manager", "architect", "head", "director",
          "sde 2", "sde-2", "sde ii", "sde 3", "sde-3", "sde iii", "sde2", "sde3")
DEV = (r"develop|engineer|programmer|sde|software|full.?stack|front.?end|back.?end|"
       r"python|java|react|node|devops|qa automation|sdet|data engineer|web|mobile|android|ios|\.net")
CITY_ALIASES = {"bangalore": ("bangalore", "bengaluru"), "mumbai": ("mumbai", "navi mumbai", "thane"),
                "pune": ("pune",)}

SENIOR_RE = re.compile("|".join(map(re.escape, SENIOR)), re.I)
DEV_RE = re.compile(DEV, re.I)


def city_matches(location: str, city: str) -> bool:
    loc = (location or "").lower()
    return any(a in loc for a in CITY_ALIASES.get(city.lower(), (city.lower(),)))
