# from motor.motor_asyncio import AsyncIOMotorDatabase
# from bson.objectid import ObjectId
# from datetime import date, datetime
# from common.config import logger

# # constant letter-to-year adjustment mapping
# LETTER_ADJUSTMENT = {"A": -1.0, "B": -0.5, "C": 0.5, "D": 1.0}

# def get_max_neg(age):
#     if age <= 24: return 3
#     if age <= 34: return 10
#     if age <= 44: return 15
#     if age <= 54: return 20
#     if age <= 64: return 22
#     if age <= 74: return 24
#     return 25

# def get_max_pos(age):
#     if age <= 34: return 12
#     if age <= 44: return 15
#     if age <= 54: return 18
#     if age <= 64: return 20
#     return 22


# # DOB To Age
# async def calculate_chronological_age(dob) -> int:
#     try:
#         if isinstance(dob, str):
#             dob = datetime.strptime(dob, '%m/%d/%Y').date()
#         elif isinstance(dob, datetime):
#             dob = dob.date()
#         # Handle date objects
#         elif not isinstance(dob, date):
#             raise ValueError("Invalid date format. Expected date, datetime, or MM/DD/YYYY string.")
            
#         today = date.today()
        
#         # Calculate base age
#         age = today.year - dob.year
        
#         # Adjust age if birthday hasn't occurred yet this year
#         if (today.month, today.day) < (dob.month, dob.day):
#             age -= 1
            
#         # Ensure age is not negative
#         return max(0, age)
        
#     except (ValueError, TypeError, AttributeError) as e:
#         logger.error(f"Error calculating age: {e}")
#         return -1  # Return -1 to indicate error


# async def calculate_biological_age(db: AsyncIOMotorDatabase, user_id: str, chronological_age: int=0) -> float:

#     adjustment = 0.0
#     questionnaire_answers = await get_questionnaire_answers(db, user_id)
#     for answer in questionnaire_answers.values():
#         if not answer:
#             continue
#         letter = answer.strip()[0].upper()  # first character (A/B/C/D)
#         if letter in LETTER_ADJUSTMENT:
#             adjustment += LETTER_ADJUSTMENT[letter]
    
#     # Cap adjustments
#     max_neg = get_max_neg(chronological_age)
#     max_pos = get_max_pos(chronological_age)

#     adjustment_cap = max(-max_neg, min(adjustment, max_pos))
#     biological_age = chronological_age + adjustment_cap
#     return biological_age, adjustment_cap, adjustment


# # Get the questionnaire answers
# async def get_questionnaire_answers(db: AsyncIOMotorDatabase, user_id: str):
#     try:
#         # Get the questionnaire document with step_2_answers and step_3_answers
#         questionnaire_doc = await db.health_assessment_responses.find_one(
#             {"user_id": ObjectId(user_id)},
#             {"step_2_answers": 1}
#         )
#         if not questionnaire_doc:
#             return {}
            
#         # Combine answers from both steps
#         step_2_answers = questionnaire_doc.get("step_2_answers", {})
        
#         # Filter answers to only include those with A:/B:/C:/D: patterns
#         graded_answers = {}
#         for key, value in step_2_answers.items():
#             if isinstance(value, str) and any(marker in value for marker in ["A:", "B:", "C:", "D:"]):
#                 graded_answers[key] = value
        
#         return graded_answers

#     except Exception as e:
#         logger.error("Error fetching questionnaire: {e}")
#         return {}

from motor.motor_asyncio import AsyncIOMotorDatabase
from bson.objectid import ObjectId
from datetime import date, datetime
from common.config import logger

# Points mapping per spec
RESPONSE_POINTS = {
    "A": 0,
    "B": 1,
    "C": 2,
    "D": 3
}

# Field → weight mapping (exactly from your Step 2)
FIELD_WEIGHTS = {
    "moderate_exercise_frequency": 1.5,   # Q1 Exercise
    "diet_quality": 1.5,                  # Q2 Diet
    "sleep_hours": 1.5,                   # Q3 Sleep
    "stress_management": 1.0,             # Q4 Stress
    "smoking_status": 2.5,                # Q5 Smoking
    "alcohol_intake": 1.0,                # Q6 Alcohol
    "bmi_status": 2.0,                    # Q7 BMI
    "mental_activity_frequency": 0.5,     # Q8 Mental stimulation
    "social_connections": 0.5,            # Q9 Social connections
    "chronic_conditions": 2.5,            # Q10 Chronic conditions
    "health_checkup_frequency": 0.5,      # Q11 General check-ups
    "dental_health": 0.5,                 # Q12 Dental health
    "energy_alertness_frequency": 0.5,    # Q13 Daytime energy
    "happiness_frequency": 0.5,           # Q14 Mood
    "pain_discomfort_frequency": 1.0,     # Q15 Pain
    "prescription_frequency": 2.0,        # Q16 Prescription medications
    "outdoor_frequency": 0.5,             # Q17 Outdoors
    "omega3_frequency": 0.5,              # Q18 Omega-3 intake
    "sugary_snacks_frequency": 0.5,       # Q19 Sugary snacks
    "overall_health_perception": 1.0      # Q20 Self-rated health
}

def get_max_neg(age: int) -> int:
    if age <= 24: return 3
    if age <= 34: return 10
    if age <= 44: return 15
    if age <= 54: return 20
    if age <= 64: return 22
    if age <= 74: return 24
    return 25

def get_max_pos(age: int) -> int:
    if age <= 34: return 12
    if age <= 44: return 15
    if age <= 54: return 18
    if age <= 64: return 20
    return 22


async def calculate_chronological_age(dob) -> int:
    try:
        if isinstance(dob, str):
            dob = datetime.strptime(dob, '%m/%d/%Y').date()
        elif isinstance(dob, datetime):
            dob = dob.date()
        elif not isinstance(dob, date):
            raise ValueError("Invalid date format for DOB.")
        today = date.today()
        age = today.year - dob.year - (1 if (today.month, today.day) < (dob.month, dob.day) else 0)
        return max(0, age)
    except Exception as e:
        logger.error(f"Error calculating age: {e}")
        return -1


async def get_questionnaire_answers(db: AsyncIOMotorDatabase, user_id: str) -> dict:
    """Return only A/B/C/D answers from step_2, uppercased and trimmed."""
    try:
        doc = await db.health_assessment_responses.find_one(
            {"user_id": ObjectId(user_id)},
            {"step_2_answers": 1}
        )
        if not doc:
            return {}
        src = doc.get("step_2_answers", {}) or {}
        out = {}
        for k, v in src.items():
            if isinstance(v, str) and v and v[0].upper() in RESPONSE_POINTS:
                out[k] = v[0].upper()
        return out
    except Exception as e:
        logger.error(f"Error fetching questionnaire: {e}")
        return {}


async def calculate_biological_age(db: AsyncIOMotorDatabase, user_id: str, chronological_age: int = 0):
    """
    Single-function version.
    Calculates biological age from step_2 answers using weights and A/B/C/D scoring.
    """
    # Get all questionnaire answers
    answers = await get_questionnaire_answers(db, user_id)

    # Weighted raw score S
    S = 0.0
    for field, weight in FIELD_WEIGHTS.items():
        resp = answers.get(field, "C")  # default to "C" (neutral)
        points = RESPONSE_POINTS.get(resp, 2)  # default 2 if invalid
        S += points * weight

    # Normalize to 0–100
    sum_weights = sum(FIELD_WEIGHTS.values())
    s_max = 3.0 * sum_weights
    r = 100.0 * S / s_max if s_max > 0 else 0.0

    # Caps
    max_neg = get_max_neg(chronological_age)
    max_pos = get_max_pos(chronological_age)

    # Age delta
    delta = -max_neg + (max_pos + max_neg) * (r / 100.0)

    raw_biological_age = chronological_age + delta
    final_biological_age = max(18.0, raw_biological_age)

    # Final results
    return {
        "biological_age": round(final_biological_age, 1),
        "adjustment_cap": round(delta, 1),
        "risk_points": round(S, 1),
        "risk_percent": round(r, 1),
        "raw_biological_age": round(raw_biological_age, 1),
        "max_negative_cap": max_neg,
        "max_positive_cap": max_pos,
        "sum_weights": round(sum_weights, 1),
        "s_max": round(s_max, 1),
    }
