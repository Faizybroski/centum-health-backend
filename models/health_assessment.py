from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator, EmailStr
import re


class HealthFormStep1Model(BaseModel):
    physician_name: str
    physician_phone: str 
    physician_location: str
    current_medications: str
    supplements: str
    allergy_medications: str
    allergy_food: str
    allergy_environmental: str
    past_medical_conditions: List[str]
    past_medical_conditions_other_text: Optional[str] = ""
    surgical_history: str
    hospitalizations: str
    family_history: List[str]
    family_history_other_text: Optional[str] = ""
    vaccination_status: str
    missing_vaccines: Optional[str] = ""

    class Config:
        extra = "forbid"
    
    @field_validator('physician_phone')
    @classmethod
    def validate_phone(cls, v):
        if not re.fullmatch(r'\+?\d{10,15}', v):
            raise ValueError('Phone number must be 10-15 digits, optionally starting with +')
        return v


# class HealthFormStep2Model(BaseModel):
#     # Diet
#     typical_diet: List[str]
#     typical_diet_other_text: Optional[str] = ""
#     dietary_restrictions: str
#     dietary_restrictions_details: Optional[str] = ""
#     fruit_veg_servings: str
#     consumes_processed_sugar: str
#     processed_sugar_details: Optional[str] = ""
#     diet_quality: str
#     omega3_frequency: str
#     sugary_snacks_frequency: str

#     # Exercise
#     exercise_days_per_week: str
#     exercise_types: List[str]
#     exercise_types_other_text: Optional[str] = ""
#     exercise_minutes: str
#     moderate_exercise_frequency: str

#     # Weight & Body
#     bmi_status: str

#     # Substance Use
#     smokes: str
#     cigarettes_per_day: Optional[str] = ""
#     smoking_status: str
#     alcohol_intake: str
#     uses_recreational_drugs: str
#     recreational_drugs_details: Optional[str] = ""

#     # Sleep Health
#     sleep_schedule: str
#     sleep_hours: str
#     sleep_quality: str
#     sleep_difficulty: str
#     daytime_sleepiness: str

#     # Mental, Social & Emotional Health
#     stress_management: str
#     stress_level: str
#     stress_sleep_effect: str
#     daily_mood: str
#     mental_activity_frequency: str
#     social_connections: str

#     # Health Maintenance & Prevention
#     chronic_conditions: str
#     health_checkup_frequency: str
#     dental_health: str
#     prescription_frequency: str
#     outdoor_frequency: str

#     # Gut Health & Health Perception
#     digestive_issues: str
#     gut_sleep_connection: str
#     overall_health_perception: str
#     additional_health_comments: str

#     class Config:
#         extra = "forbid"  # Prevent unknown keys


class HealthFormStep2Model(BaseModel):
    # Diet
    typical_diet: List[str]
    typical_diet_other_text: Optional[str] = " "
    dietary_restrictions: str
    dietary_restrictions_details: Optional[str] = " "
    fruit_veg_servings: str
    consumes_processed_sugar: str
    processed_sugar_details: Optional[str] = " "
    diet_quality: str
    omega3_frequency: str
    sugary_snacks_frequency: str

    # Exercise
    exercise_days_per_week: str
    exercise_types: List[str]
    exercise_types_other_text: Optional[str] = " "
    exercise_minutes: str
    moderate_exercise_frequency: str

    # Weight & Body
    bmi_status: str

    # Substance Use
    smokes: str
    cigarettes_per_day: Optional[str] = " "
    smoking_status: str
    alcohol_intake: str
    uses_recreational_drugs: str
    recreational_drugs_details: Optional[str] = " "

    # Sleep Health
    sleep_schedule: str
    # sleep_schedule_weekdays: Optional[str] = " "
    # sleep_schedule_weekends: Optional[str] = " "
    sleep_hours: str
    sleep_quality: str
    sleep_difficulty: str
    daytime_sleepiness: str
    night_wakings_frequency: str
    wake_refreshed_frequency: str
    take_nap_during_day: str = ""
    nap_duration_minutes: Optional[str] = " "
    sleep_environment: List[str]
    uses_electronics_before_bed: str
    caffeine_after_2pm: str
    alcohol_in_evening: str
    exercise_timing_regular: str
    sleep_disorder_diagnosed: str
    sleep_disorder_details: Optional[str] = " "
    snore_or_apnea_observed: str
    restless_legs: str
    frequent_nightmares: str

    # Mental, Social & Emotional Health
    stress_management: str
    stress_level: str
    stress_sleep_effect: str
    daily_mood: str
    mental_activity_frequency: str
    social_connections: str
    energy_alertness_frequency: str
    happiness_frequency: str
    pain_discomfort_frequency: str

    # Health Maintenance & Prevention
    chronic_conditions: str
    health_checkup_frequency: str
    dental_health: str
    prescription_frequency: str
    outdoor_frequency: str

    # Gut Health & Health Perception
    digestive_issues: str
    gut_sleep_connection: str
    overall_health_perception: str

    # Additional Comments
    additional_health_comments: Optional[str] = ""

    class Config:
        extra = "forbid"  # Prevent unknown keys



class HealthFormStep3Model(BaseModel):
    primary_health_goals: List[str]
    primary_health_goals_other_text: Optional[str] = ""
    health_concerns: str
    preferred_communication: List[str]
    intervention_level: str
    interest_areas: List[str]
    interest_areas_other_text: Optional[str] = ""

    class Config:
        extra = "forbid"


class HealthFormStep4Model(BaseModel):
    privacy_policy_consent: bool = False
    informational_insights_agreement: bool = False
    terms_of_service_agreement: bool = False
    followup_contact_consent: bool = False

    class Config:
        extra = "forbid"


class SaveStepRequest(BaseModel):
    step_number: int = Field(..., ge=1, le=4)
    form_data: Dict[str, Any]


class CompareRequest(BaseModel):
    report_id_1: str
    report_id_2: str


class VO2MaxUpdate(BaseModel):
    vo2_max: float

class UserEmailDTO(BaseModel):
    email: EmailStr
    name: str | None = None