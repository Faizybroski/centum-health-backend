"""
CENTUM HEALTH CLINICAL SUMMARY GENERATOR
Complete Template for AI-Generated Clinical Summaries
Version 2.0 - July 2025
Supports All 16 Biomarker Categories & 100+ Tests
"""

import json
from typing import Dict, Any

from azure.ai.inference.aio import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential

from data_processing.biomarkers_range import biomarker_with_name_and_range
from common.config import settings, logger


async def generate_clinical_summary_grok(               # ← step 2a
    gender: str,
    lab_results,
    questionnaire: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Async version of the Centum Health clinical‑summary generator.
    Returns the parsed JSON object.
    """    
    print("Generating summary started...")
    logger.info("Generating summary started...")
    try:
        prompt = f"""You're centum blood report summarizre AI.
        ## YOUR TASK
            Your task is to provde a json summary of the blood report using the given predfiend ranges for all the test.
            Check every test value and compare it with the predefiend ranges given to you, and map them to good,normal or critical biomarkers with using your knowledge about the bio-markes(lab test), 
            You will also be provided with patient personal questions, read them carefully. 
            After reading the patient questionaries give a action_plan which will contain four values diet(do's and dont), exercise(do's and dont), sleep(do's and dont) and supplement(do's and dont).
            Give me summary of his overall health.
            After that also provide me Critical Concers that the patient need to look after(if any).

        #  INPUT
            ## Predefined biomarkers range : {biomarker_with_name_and_range}

            ## User Information
                user gender : {gender}
                Blood Report : {lab_results}
                Patient Questionaries : {questionnaire}
        
        # OUTPUT
            1) The output stricly must be JSON ouput with no extra commentaires or string.
            2) The JSON must contains there fours main keys, good, normal, critical and action_plan.,
                if there are any invalid bio-markers, thet you cant give result of give me there name and there short explanation why they are invalid.
                for e.g., {{ 
                
                    good : {{'testosterone_total':'18.5','fecal_calprotectin':'35',......}},
                    normal:{{'vitamin_b12':'385','tsh':....}},
                    critical:{{'homa_ir':'4.1',......}},

                    action_plan:{{
                        diet:{{'do':["eat vegetables","drink more water",...],"dont":["stop eating sugar",...]}},
                        exercise:{{'do':["include cardion","yoga",...],"dont":["stop heavy lifting",...]}},
                        sleep:{{'do':["take proper 8 hour of sleep",...],"dont":["do not sleep in light",...]}},
                        supplement:{{'do':["protein powder","vitamin D",...],"dont":["vitamin B12",...]}},
                    }}
                    summary:"Your overall blood report suggest that......"
                    critical_concerns:["your blood sugar is ver high consult doctor now......","stop smoking "]
                    invalid_biomarkers{{"urine_protein":"dont have any value",....}}
                }}
                
        # MAKE SURE
            ## Make sure to map all the valid test that are present in the patient blood report.
            ## The comparison of blood report test will be with the predefiend biomarkers range only.
            ## Make sure at the end of reuslt the addition of length of good,normal and critical and invalid_biomarkers must be equal to the total number of biomarkers(lab test) present inside the blood test report.
            ## While generating answer make sure to generate the test name similar to predefiedn biomarkers range. for e.g., if the blood report contains 'FASTING GlUCOSE' it must be converted to 'fasting_glucose' as written in predefined biomarker ranges.
    """
        logger.info("Generating summary using Grok...")
        endpoint = settings.AZURE_GROK_ENDPOINT
        model_name = settings.AZURE_GROK_DEPLOYMENT
        key = settings.AZURE_GROK_API_KEY
    
        async with ChatCompletionsClient(endpoint, AzureKeyCredential(key), credential_scopes=["https://cognitiveservices.azure.com/.default"]) as client:
            resp = await client.complete(
            messages=[
                SystemMessage(content="You are a meticulous medical summarizer."),
                UserMessage(content=prompt)
            ],
            model=model_name,
        )
        assistant_raw = resp.choices[0].message.content
    
        summary_obj = json.loads(assistant_raw)
        logger.info("Summary generated successfully.")
        return summary_obj
    except Exception as e:
        logger.error(f"Error generating summary: {str(e)}")
        return None
        