from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import json
import re
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

with open("universities.json") as f:
    universities = json.load(f)

# --- Models ---
class ProfileInput(BaseModel):
    cgpa: float
    field: str
    budget_per_semester: int
    english_proof: str
    city_preference: Optional[str] = "any"
    work_experience: Optional[str] = "none"

class SOPInput(BaseModel):
    sop_text: str
    target_university: Optional[str] = ""
    target_programme: Optional[str] = ""

# --- University Matching ---
def cgpa_to_german(cgpa_10):
    if cgpa_10 >= 9.5: return 1.0
    elif cgpa_10 >= 9.0: return 1.3
    elif cgpa_10 >= 8.5: return 1.7
    elif cgpa_10 >= 8.0: return 2.0
    elif cgpa_10 >= 7.5: return 2.3
    elif cgpa_10 >= 7.0: return 2.7
    elif cgpa_10 >= 6.5: return 3.0
    elif cgpa_10 >= 6.0: return 3.3
    elif cgpa_10 >= 5.5: return 3.7
    else: return 4.0

def match_universities(profile: ProfileInput):
    results = {"safe": [], "moderate": [], "reach": []}
    
    for uni in universities:
        # Filter by budget
        if uni["fees_per_semester"] > profile.budget_per_semester:
            continue
        
        # Filter by field
        field_map = {
            "cs": ["Computer Science", "Web Engineering", "Information Technology"],
            "ds": ["Data Science", "Computer Science"],
            "web": ["Web Engineering", "Computer Science"],
            "it": ["Information Technology", "Computer Science"]
        }
        allowed_fields = field_map.get(profile.field.lower(), [uni["field"]])
        if uni["field"] not in allowed_fields:
            continue
        
        # City preference
        if profile.city_preference and profile.city_preference.lower() not in ["any", ""]:
            if uni["city"].lower() not in profile.city_preference.lower() and uni["city_size"].lower() not in profile.city_preference.lower():
                continue
        
        # Classify tier
        diff = profile.cgpa - uni["cgpa_minimum"]
        if diff >= 1.5:
            tier = "safe"
        elif diff >= 0.5:
            tier = "moderate"
        elif diff >= -0.5:
            tier = "reach"
        else:
            continue  # Too far below requirement
        
        results[tier].append({
            "id": uni["id"],
            "university_name": uni["university_name"],
            "programme_name": uni["programme_name"],
            "city": uni["city"],
            "state": uni["state"],
            "cgpa_minimum": uni["cgpa_minimum"],
            "fees_per_semester": uni["fees_per_semester"],
            "deadline_winter": uni["deadline_winter"],
            "english_requirement": uni["english_requirement"],
            "application_via": uni["application_via"],
            "programme_url": uni["programme_url"],
            "notes": uni["notes"],
            "qs_ranking": uni["qs_ranking"],
            "tier": tier
        })
    
    return results

@app.post("/match")
def match(profile: ProfileInput):
    results = match_universities(profile)
    total = sum(len(v) for v in results.values())
    return {"results": results, "total": total}

# --- SOP Analyser ---
GENERIC_PHRASES = [
    ("knowledge is power", "Replace with a specific insight or experience that shaped you"),
    ("since childhood", "Too vague. Mention a specific age or event instead"),
    ("i have always been passionate", "Show the passion through a story, not a claim"),
    ("in today's world", "Generic opener. Start with your specific experience"),
    ("i am a hardworking person", "Show it with an example, don't claim it"),
    ("i am a quick learner", "Prove it with a concrete learning experience"),
    ("to pursue my dreams", "What specific dream? Be precise about your goal"),
    ("i want to contribute to society", "Too vague. What specific problem will you solve?"),
    ("this prestigious university", "Name the university and cite a specific module/professor"),
    ("world-class university", "Name what specifically attracts you to this programme"),
    ("exposure to various technologies", "List the specific technologies and what you learned"),
    ("it is a well-known fact", "Delete this. Just state the fact directly"),
    ("needless to say", "If it's needless, don't say it. Remove the whole sentence"),
    ("at this juncture", "Replace with specific timing that matters to your story"),
]

def analyse_sop(sop: SOPInput):
    text = sop.sop_text.strip()
    words = text.split()
    word_count = len(words)
    sentences = re.split(r'[.!?]+', text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
    
    score = 100
    flags = []
    positives = []

    # 1. Word count
    if word_count < 400:
        score -= 20
        flags.append({
            "type": "length",
            "found": f"{word_count} words",
            "suggestion": "SOP is too short. Aim for 800-1000 words for German universities."
        })
    elif word_count > 1200:
        score -= 10
        flags.append({
            "type": "length",
            "found": f"{word_count} words",
            "suggestion": "SOP is too long. Trim to 800-1000 words. Admissions officers skip long SOPs."
        })
    else:
        positives.append(f"Good length: {word_count} words")

    # 2. Quantification
    numbers = re.findall(r'\b\d+[%+]?\b', text)
    if len(numbers) < 2:
        score -= 15
        flags.append({
            "type": "quantification",
            "found": f"Only {len(numbers)} numbers found",
            "suggestion": "Add specific numbers: accuracy %, team size, time saved, project scale, CGPA"
        })
    else:
        positives.append(f"Contains {len(numbers)} quantified facts — good")

    # 3. Generic phrases
    text_lower = text.lower()
    for phrase, suggestion in GENERIC_PHRASES:
        if phrase in text_lower:
            score -= 8
            flags.append({
                "type": "generic_phrase",
                "found": f'"{phrase}"',
                "suggestion": suggestion
            })

    # 4. University-specific mention
    if sop.target_university:
        uni_name = sop.target_university.lower()
        short_name = uni_name.split()[-1] if uni_name else ""
        if uni_name not in text_lower and short_name not in text_lower:
            score -= 15
            flags.append({
                "type": "specificity",
                "found": f"Target university '{sop.target_university}' not mentioned",
                "suggestion": f"Name {sop.target_university} directly and cite 1-2 specific modules, professors, or research groups that attract you"
            })
        else:
            positives.append(f"University name mentioned — good")

    # 5. Future goals / career intent
    goal_words = ["goal", "aim", "aspire", "plan to", "intend", "career", "future", "become", "work as"]
    has_goals = any(w in text_lower for w in goal_words)
    if not has_goals:
        score -= 10
        flags.append({
            "type": "goals",
            "found": "No clear career goals found",
            "suggestion": "Add a clear paragraph: what role do you want, in what type of company, solving what problem, in 5 years?"
        })
    else:
        positives.append("Career goals are mentioned")

    # 6. Opening hook
    first_sentence = sentences[0] if sentences else ""
    generic_openers = ["i was born", "i am writing", "i wish to", "this statement", "my name is"]
    if any(op in first_sentence.lower() for op in generic_openers):
        score -= 8
        flags.append({
            "type": "opening",
            "found": f'Weak opener: "{first_sentence[:80]}..."',
            "suggestion": "Open with a story, problem you encountered, or a striking insight. Not 'I am writing to apply...'"
        })
    else:
        positives.append("Opening does not use a generic opener — good")

    # 7. Word repetition
    word_freq = {}
    for word in words:
        w = word.lower().strip(".,!?")
        if len(w) > 5:
            word_freq[w] = word_freq.get(w, 0) + 1
    repeated = [(w, c) for w, c in word_freq.items() if c >= 5]
    if repeated:
        score -= 5
        for word, count in repeated[:3]:
            flags.append({
                "type": "repetition",
                "found": f'"{word}" used {count} times',
                "suggestion": f"Replace some instances of '{word}' with synonyms to improve readability"
            })

    score = max(0, min(100, score))

    if score >= 80:
        tier = "Strong"
        tier_color = "green"
    elif score >= 60:
        tier = "Competitive"
        tier_color = "orange"
    else:
        tier = "Needs Work"
        tier_color = "red"

    # Top 3 priorities
    priorities = [f["suggestion"] for f in flags[:3]]

    return {
        "score": score,
        "tier": tier,
        "tier_color": tier_color,
        "word_count": word_count,
        "flags": flags,
        "positives": positives,
        "top_priorities": priorities
    }

@app.post("/analyse-sop")
def analyse(sop: SOPInput):
    return analyse_sop(sop)

@app.get("/")
def root():
    return {"message": "ScratchToTopNotch API is running"}
