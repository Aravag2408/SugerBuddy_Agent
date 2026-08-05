from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()

TEAM_INFO = {
    "group_batch_order_number": "TODO_FILL_BEFORE_SUBMISSION",
    "team_name": "SugarBuddy",
    "students": [
        {"name": "Arava Gendelman", "email": "aravag@campus.technion.ac.il"},
        {"name": "Aya Grabarsky", "email": "ayagrabarsky@campus.technion.ac.il"},
        {"name": "Sofia Torgovezky", "email": "sofiat@campus.technion.ac.il"},
    ],
}


@app.get("/api/team_info")
def team_info():
    return TEAM_INFO


ARCHITECTURE_DIAGRAM_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "architecture" / "pipeline_diagram.png"
)


@app.get("/api/model_architecture")
def model_architecture():
    return FileResponse(ARCHITECTURE_DIAGRAM_PATH, media_type="image/png")


import json

from agent_pipeline import (
    CGM_EVENT_SYSTEM_PROMPT,
    CONFIDENCE_SYSTEM_PROMPT,
    PARENT_SUMMARY_SYSTEM_PROMPT,
    REACT_SYSTEM_PROMPT_BASE,
)

_SYSTEM_PROMPTS_BY_MODULE = {
    "CGM Event": CGM_EVENT_SYSTEM_PROMPT,
    "ReAct Agent": REACT_SYSTEM_PROMPT_BASE,
    "Confidence Classification": CONFIDENCE_SYSTEM_PROMPT,
    "Parent Summary": PARENT_SUMMARY_SYSTEM_PROMPT,
}


def _step(module: str, user_prompt_payload, response: dict) -> dict:
    if isinstance(user_prompt_payload, str):
        user_prompt = user_prompt_payload
    else:
        user_prompt = json.dumps(user_prompt_payload, ensure_ascii=False, indent=2)
    return {
        "module": module,
        "prompt": {
            "system_prompt": _SYSTEM_PROMPTS_BY_MODULE[module],
            "user_prompt": user_prompt,
        },
        "response": response,
    }


# --- Example 1: glucose spiking to 260, no follow-up needed (real run, 2026-08-05) ---

_EX1_ANOMALY = {
    "type": "glucose_extreme",
    "severity": "urgent",
    "direction": "high",
    "message": "Glucose has risen to 260 and is increasing rapidly.",
    "details": {"glucose": 260, "trend": "rising fast"},
}
_EX1_ANSWERS = {
    "ate_recently": True,
    "carb_count_accurate": True,
    "exercised_last_4h": False,
    "stressed_last_30min": False,
    "drank_water_today": True,
    "hot_weather_last_30min": False,
    "correction_dose_last_3h": False,
    "phone_sensor_check_last_hour": True,
    "accurate_meals_today": True,
    "finger_stick_or_calibration_recent": False,
}
_EX1_TABLE_MATCHES = [
    {
        "category": "תזונה וארוחות מורכבות",
        "cause": "פחמימות נסתרות: \"פחמימות חבויות\" ברטבים, מאכלים מעובדים או סלטים קנויים",
        "explanation": "באוכל היה סוכר חבוי (כמו קטשופ, רטבים או סוכר סמוי במאכל מעובד) שלא שמנו לב אליו, ולכן לא נתנו עליו אינסולין.",
        "state": "היפר",
        "time_to_effect": "שעה עד שעתיים",
    },
    {
        "category": "תזונה וארוחות מורכבות",
        "cause": "עודף פחמימות: אכילת פחמימות מעבר למה שחושב או ללא כיסוי אינסולין כלל",
        "explanation": "נכנס המון סוכר מהאוכל לתוך הדם, אבל לא נתנו מספיק אינסולין (מפתחות) כדי לפתוח את הדלתות ולהכניס אותו לתאים.",
        "state": "היפר",
        "time_to_effect": "30 דקות עד שעתיים",
    },
    {
        "category": "פיזיולוגיה ובריאות",
        "cause": "עייפות קיצונית: לילה ללא שינה מספקת או שינה לא רגועה",
        "explanation": "כשהגוף עייף ולא ישן טוב, הוא חווה סוג של לחץ פיזי (סטרס), מה שיוצר חומה ומפריע לאינסולין להוריד את הסוכר.",
        "state": "היפר",
        "time_to_effect": "במהלך כל היום שאחרי האירוע",
    },
]
_EX1_RAG_SNIPPET = (
    "American Diabetes Association -- Hyperglycemia (High Blood Glucose)\n\n"
    "Hyperglycemia is the technical term for high blood glucose (blood sugar). "
    "High blood glucose happens when the body has too little insulin or when the "
    "body can't use insulin properly.\n\nWhat causes hyperglycemia?\nA number of "
    "things can cause hyperglycemia:\n- If you have type 1, you may not have given "
    "yourself enough insulin.\n- If you have type 2, your body may have enough "
    "insulin, but it is not as effective as it should be.\n- You ate more than "
    "planned or exercised less than planned.\n- You have stress from an illness, "
    "such as a cold or flu.\n- You have other stress, such as family conflicts or "
    "school or dating problems.\n- You may have experienced the dawn phenomenon "
    "(a surge of hormones that the body produces daily around 4:00 a.m. to 5:00 "
    "a.m.).\n\nWhat are the symptoms of hyperglycemia?\nThe signs and hyperglycemia "
    "symptoms include the following: high blood glucose, high levels of glucose in "
    "the urine, frequent urination, increased thirst.\n\nHow do I treat "
    "hyperglycemia?\nYou can often lower your blood glucose level by exercising. "
    "However, if your blood glucose is above 240 mg/dl, check your urine for "
    "ketones. If you have ketones, do not exercise -- exercising when ketones are "
    "present may make your blood glucose level go even higher. Cutting down on the "
    "amount of food you eat might also help. If exercise and changes in diet don't "
    "work, your doctor may change the amount of your medication or insulin, or the "
    "timing of when you take it.\n\nWhat if high glucose levels go untreated?\n"
    "Hyperglycemia can be a serious problem if you don't treat it. If you fail to "
    "treat hyperglycemia, a condition called ketoacidosis (diabetic coma) could "
    "occur. Ketoacidosis develops when your body doesn't have enough insulin, so it "
    "breaks down fats for energy, producing waste products called ketones that "
    "build up in the blood. Ketoacidosis is life-threatening and needs immediate "
    "treatment. Symptoms include: shortness of breath, breath that smells fruity, "
    "nausea and vomiting, very dry mouth.\n\nHow can I prevent hyperglycemia?\n"
    "Your best bet is to practice good diabetes management and learn to detect "
    "hyperglycemia so you can treat it early -- before it gets worse."
)
_EX1_FINDINGS = [
    {
        "cause": "עודף פחמימות: אכילת פחמימות מעבר למה שחושב או ללא כיסוי אינסולין כלל",
        "evidence": "הייתה ארוחה לאחרונה, והסוכר גבוה מאוד ועולה מהר. לא הייתה פעילות גופנית ב-4 השעות האחרונות, ולא הייתה זריקת תיקון ב-3 השעות האחרונות, כך שכיסוי האינסולין לא נראה מספק בזמן הנוכחי.",
        "source": "table",
    },
    {
        "cause": "פחמימות נסתרות: \"פחמימות חבויות\" ברטבים, מאכלים מעובדים או סלטים קנויים",
        "evidence": "הייתה אכילה לאחרונה, והעלייה המהירה יכולה להתאים לפחמימות שלא נכללו בספירה, למשל מרטבים או מזון מעובד. אין מידע נוסף שסותר זאת.",
        "source": "table",
    },
    {
        "cause": "חוסר אינסולין או אינסולין לא מספק",
        "evidence": "לפי ה-ADA, היפרגליקמיה יכולה להתרחש כשיש מעט מדי אינסולין או כשלא נתנו מספיק אינסולין. זה תואם ערך 260 ועולה במהירות, במיוחד כשלא ניתנה זריקת תיקון לאחרונה.",
        "source": "reference",
    },
]
_EX1_SCORED_FINDINGS = [
    {
        "cause": "עודף פחמימות: אכילת פחמימות מעבר למה שחושב או ללא כיסוי אינסולין כלל",
        "evidence": "הייתה ארוחה לאחרונה, והסוכר גבוה מאוד ועולה מהר. לא הייתה פעילות גופנית ב-4 השעות האחרונות, ולא הייתה זריקת תיקון ב-3 השעות האחרונות, כך שכיסוי האינסולין לא נראה מספק בזמן הנוכחי.",
        "confidence": "medium",
        "rationale": "יש התאמה סבירה בין אכילה לאחרונה לבין עלייה חדה בגלוקוז, אך מאחר שנמסר שספירת הפחמימות הייתה מדויקת אין כאן תמיכה ישירה חזקה לעודף פחמימות.",
    },
    {
        "cause": "פחמימות נסתרות: \"פחמימות חבויות\" ברטבים, מאכלים מעובדים או סלטים קנויים",
        "evidence": "הייתה אכילה לאחרונה, והעלייה המהירה יכולה להתאים לפחמימות שלא נכללו בספירה, למשל מרטבים או מזון מעובד. אין מידע נוסף שסותר זאת.",
        "confidence": "low",
        "rationale": "ההסבר אפשרי בלבד, אך ספירת הפחמימות המדויקת מפחיתה את הסבירות שפחמימות חבויות הן הסיבה.",
    },
    {
        "cause": "חוסר אינסולין או אינסולין לא מספק",
        "evidence": "לפי ה-ADA, היפרגליקמיה יכולה להתרחש כשיש מעט מדי אינסולין או כשלא נתנו מספיק אינסולין. זה תואם ערך 260 ועולה במהירות, במיוחד כשלא ניתנה זריקת תיקון לאחרונה.",
        "confidence": "high",
        "rationale": "זהו הסבר ישיר וחזק לגלוקוז גבוה ועולה במהירות, ובפרט כשלא ניתנה זריקת תיקון לאחרונה.",
    },
]
_EX1_PARENT_SUMMARY = (
    "האירוע היה עלייה חדה בגלוקוז ל‑260, עם מגמה של עלייה מהירה, ולכן מדובר במצב "
    "שדורש תשומת לב. לפי מה שהנער/ה דיווח/ה, הייתה אכילה לאחרונה, ספירת הפחמימות "
    "הוגדרה כמדויקת, לא הייתה פעילות גופנית ב‑4 השעות האחרונות, לא היה סטרס, "
    "ונבדק חיישן הטלפון בשעה האחרונה.\n\nהאפשרויות הסבירות ביותר הן: 1) חוסר "
    "אינסולין או אינסולין לא מספק (ביטחון: גבוה) — זה מתאים במיוחד לעלייה מהירה "
    "ולכך שלא ניתנה זריקת תיקון לאחרונה; 2) עודף פחמימות לעומת הכיסוי בפועל "
    "(ביטחון: בינוני) — ייתכן שהיה יותר פחמימות ממה שנראה או שכיסוי האינסולין "
    "לא הספיק; 3) פחמימות נסתרות במזון (ביטחון: נמוך) — למשל מרטבים או מזון "
    "מעובד שלא נכללו בספירה. מומלץ לבצע עכשיו בדיקת סוכר באצבע/לאמת את הקריאה, "
    "ולפעול לפי הנחיות התיקון שניתנו על ידי הצוות הרפואי אם הערך ממשיך לעלות."
)

_EXAMPLE_1_STEPS = [
    _step("CGM Event", "הסוכר קפץ ל-260 ועולה מהר", _EX1_ANOMALY),
    _step(
        "ReAct Agent",
        {
            "anomaly": _EX1_ANOMALY,
            "questionnaire_answers": _EX1_ANSWERS,
            "notes": "",
            "candidate_causes": _EX1_TABLE_MATCHES,
            "reference_text": _EX1_RAG_SNIPPET,
        },
        {"need_more_info": False, "followup_question": None, "findings": _EX1_FINDINGS},
    ),
    _step(
        "Confidence Classification",
        {"anomaly": _EX1_ANOMALY, "questionnaire_answers": _EX1_ANSWERS, "findings": _EX1_FINDINGS},
        {"findings": _EX1_SCORED_FINDINGS},
    ),
    _step(
        "Parent Summary",
        {"anomaly": _EX1_ANOMALY, "questionnaire_answers": _EX1_ANSWERS, "findings": _EX1_SCORED_FINDINGS},
        {"parent_summary": _EX1_PARENT_SUMMARY},
    ),
]

# --- Example 2: glucose dropping to 65, no follow-up needed (real run, 2026-08-05) ---

_EX2_ANOMALY = {
    "type": "glucose_extreme",
    "severity": "warning",
    "direction": "low",
    "message": "Glucose dropped to 65 unexpectedly.",
    "details": {"glucose_value": 65, "trend": "dropped suddenly", "unclear_cause": True},
}
_EX2_ANSWERS = dict(_EX1_ANSWERS)  # identical answer pattern was used in this live run too
_EX2_TABLE_MATCHES = [
    {
        "category": "דילוג על ארוחות",
        "cause": "פספוס ארוחה: לא אכלה ארוחת בוקר, צהריים או ערב",
        "explanation": "הגוף ממשיך לקבל את אינסולין הרקע שלו, אבל לא נכנס אוכל שיאזן אותו, ולכן רמת הסוכר יורדת.",
        "state": "היפו",
        "time_to_effect": "שעתיים",
    },
    {
        "category": "תזונה וחישוב פחמימות",
        "cause": "שאריות אוכל: אכלה פחות ממה שדיווחה למשאבה/לעט",
        "explanation": "הגוף קיבל אינסולין בשביל צלחת מלאה, אבל הילדה השאירה חצי מהאוכל בצלחת – אז חסר אוכל בבטן.",
        "state": "היפו",
        "time_to_effect": "חצי שעה",
    },
    {
        "category": "תזונה וחישוב פחמימות",
        "cause": "שינוי לו\"ז: שינוי בשעת הארוחה (אינסולין פועל ללא מזון זמין)",
        "explanation": "השעה של הארוחה הקבועה השתנתה, והאינסולין בגוף התחיל לפעול לפני שהאוכל נכנס למערכת.",
        "state": "היפו",
        "time_to_effect": "1 עד 3 שעות",
    },
]
_EX2_RAG_SNIPPET = (
    "American Diabetes Association -- Hypoglycemia (Low Blood Glucose): Causes and "
    "Prevention\n\nWhat causes low blood glucose?\nHypoglycemia (or low blood "
    "glucose) is common for people with type 1 diabetes. It also can occur in "
    "people with type 2 diabetes taking insulin or certain diabetes medications.\n\n"
    "Common causes of low blood glucose:\n- Insulin and similar medications: too "
    "much insulin or certain diabetes medications, miscalculating carbs eaten, "
    "accidentally injecting the wrong insulin type, injecting directly into the "
    "muscle instead of just under the skin.\n- What you eat or drink: not eating "
    "enough food, eating fewer carbs than planned, skipping a meal or snack, "
    "delayed meals, alcohol (especially on an empty stomach) -- alcohol use can "
    "cause dangerously low blood glucose, including many hours after use.\n- "
    "Physical activity: exercise can lower blood glucose and increase insulin "
    "sensitivity for hours afterward, including overnight while sleeping.\n\nCan "
    "low blood glucose be prevented?\nKeep blood glucose in your target range, "
    "track personal low-blood-glucose symptoms so you can act faster, and monitor "
    "with a glucose meter or CGM. Check more frequently around meals, physical "
    "activity, bedtime, and when routines change (new insulin routine, schedule "
    "change, travel).\n\nAmerican Diabetes Association -- Signs, Symptoms, and "
    "Treatment for Hypoglycemia\n\nWhat are the signs of low blood glucose "
    "(hypoglycemia)?\nSigns and symptoms are caused by release of the "
    "\"fight-or-flight\" hormone epinephrine (adrenaline), and can develop "
    "quickly: feeling shaky, nervous or anxious, sweating/chills/clamminess, "
    "irritability, confusion, fast heartbeat, lightheadedness or dizziness, "
    "hunger, nausea, pallor, sleepiness, weakness, blurred vision, tingling or "
    "numbness in lips/tongue/cheeks, headaches, coordination problems, and in "
    "some cases seizures.\n\nHypoglycemia unawareness: for most people, symptoms "
    "start below 70 mg/dL, but some people can have a low with no symptoms at all "
    "(\"hypoglycemia unawareness\"), which increases risk of severe "
    "hypoglycemia, including at night.\n\nHow do you treat low blood glucose? The "
    "\"15-15 Rule\":\nIf blood glucose is 70 mg/dL or below: consume 15 grams of "
    "fast-acting carbohydrates, wait 15 minutes, then recheck. If still below "
    "70 mg/dL (or not trending up), have another 15 grams. Once above 70 mg/dL "
    "(or trending up) and not eating a meal soon, have a protein+carbohydrate "
    "snack to prevent it dropping again. Fast-acting carb examples: glucose "
    "tablets, glucose gel, 1/2 cup of juice or regular soda, a tablespoon of "
    "sugar/corn syrup/honey, or hard candies/jellybeans (check label for 15g "
    "equivalent).\n\n## HYPOGLYCEMIA (NIDDK)\n\nLow blood glucose, also called low "
    "blood sugar or hypoglycemia, occurs when the level of glucose in your blood "
    "drops below what is healthy for you. Symptoms develop rapidly and range from "
    "mild (shakiness, hunger, dizziness) to severe (loss of consciousness, "
    "seizures). Severely low blood glucose can cause serious complications, "
    "including passing out, coma, or death.\n\nCauses of low blood glucose:\n- "
    "Insulin and diabetes medicines (sulfonylureas, meglitinides) that lower "
    "glucose levels.\n- Insufficient carbohydrate intake or skipped/delayed "
    "meals.\n- Fasting while taking glucose-lowering medications.\n- Increased "
    "physical activity (can lower blood glucose for up to 24 hours after).\n- "
    "Alcohol consumption without adequate food.\n- Illness that prevents normal "
    "eating."
)
_EX2_FINDINGS = [
    {
        "cause": "שאריות אוכל: אכלה פחות ממה שדיווחה למשאבה/לעט",
        "evidence": "האכלה לאחרונה = כן, אבל אם אכלה פחות פחמימות ממה שדווח היינו מצפים להיפו זמן קצר לאחר הארוחה; זה מתאים במיוחד לירידה חדה ב-65. עם זאת, 'carb_count_accurate' סומן כן, ולכן התמיכה חלקית בלבד.",
        "source": "table",
    },
    {
        "cause": "שינוי לו\"ז: שינוי בשעת הארוחה (אינסולין פועל ללא מזון זמין)",
        "evidence": "סוכר נמוך יכול לקרות כשאינסולין פועל לפני שהאוכל זמין, במיוחד סביב שינויים בזמני ארוחות. כאן יש ירידה פתאומית אחרי שאכלה לאחרונה, מה שיכול להתאים לדפוס כזה.",
        "source": "table",
    },
    {
        "cause": "לא אכלה מספיק / דילוג על ארוחה",
        "evidence": "הנחיית ADA/NIDDK מציינת שדלוג או עיכוב בארוחה, או אכילה לא מספקת, הם גורמים שכיחים להיפוגליקמיה. עם זאת, בשאלון סומן שאכלה לאחרונה, ולכן זה פחות נתמך במקרה הזה.",
        "source": "reference",
    },
]
_EX2_SCORED_FINDINGS = [
    {
        "cause": "שאריות אוכל: אכלה פחות ממה שדיווחה למשאבה/לעט",
        "evidence": "האכלה לאחרונה = כן, אבל אם אכלה פחות פחמימות ממה שדווח היינו מצפים להיפו זמן קצר לאחר הארוחה; זה מתאים במיוחד לירידה חדה ב-65. עם זאת, 'carb_count_accurate' סומן כן, ולכן התמיכה חלקית בלבד.",
        "confidence": "medium",
        "rationale": "יש התאמה אפשרית בין ירידה חדה סמוך לאכילה לבין אכילה פחותה מהמדווח, אך דיווח מדויק על ספירת פחמימות מחליש את ההשערה.",
    },
    {
        "cause": "שינוי לו\"ז: שינוי בשעת הארוחה (אינסולין פועל ללא מזון זמין)",
        "evidence": "סוכר נמוך יכול לקרות כשאינסולין פועל לפני שהאוכל זמין, במיוחד סביב שינויים בזמני ארוחות. כאן יש ירידה פתאומית אחרי שאכלה לאחרונה, מה שיכול להתאים לדפוס כזה.",
        "confidence": "low",
        "rationale": "העדות מתארת מנגנון אפשרי, אך אין בשאלון אינדיקציה ממשית לשינוי בשעת הארוחה ולכן הקשר עקיף בלבד.",
    },
    {
        "cause": "לא אכלה מספיק / דילוג על ארוחה",
        "evidence": "הנחיית ADA/NIDDK מציינת שדלוג או עיכוב בארוחה, או אכילה לא מספקת, הם גורמים שכיחים להיפוגליקמיה. עם זאת, בשאלון סומן שאכלה לאחרונה, ולכן זה פחות נתמך במקרה הזה.",
        "confidence": "low",
        "rationale": "למרות שזהו גורם שכיח להיפוגליקמיה, העובדה שאכלה לאחרונה הופכת אותו לפחות סביר במקרה זה.",
    },
]
_EX2_PARENT_SUMMARY = (
    "הייתה ירידה חדה בסוכר ל־65, והמערכת סימנה זאת כאירוע נמוך לא צפוי. לפי מה "
    "שהנער/ה דיווח/ה, הוא/היא אכל/ה לאחרונה, ספירת הפחמימות הייתה מדויקת, לא "
    "הייתה פעילות גופנית, לא היה סטרס ולא נלקחה מנת תיקון לאחרונה.\n\nהסברים "
    "אפשריים לפי הסבירות: 1) בסבירות בינונית — ייתכן שנאכלה פחות כמות מזון ממה "
    "שדווח למשאבה/לעט, למרות שהדיווח נראה מדויק; 2) בסבירות נמוכה — ייתכן שהיה "
    "שינוי בתזמון הארוחה כך שהאינסולין פעל לפני שהמזון היה זמין; 3) בסבירות "
    "נמוכה — ייתכן שלא נאכלה כמות מספקת או שהייתה ארוחה חסרה. הצעה מעשית: אם זה "
    "קורה שוב, מומלץ לבדוק סוכר באצבע כדי לאמת את הקריאה ולהכין מקור סוכר מהיר "
    "בהישג יד."
)

_EXAMPLE_2_STEPS = [
    _step("CGM Event", "הסוכר ירד פתאום ל-65 בלי שהבנו למה", _EX2_ANOMALY),
    _step(
        "ReAct Agent",
        {
            "anomaly": _EX2_ANOMALY,
            "questionnaire_answers": _EX2_ANSWERS,
            "notes": "",
            "candidate_causes": _EX2_TABLE_MATCHES,
            "reference_text": _EX2_RAG_SNIPPET,
        },
        {"need_more_info": False, "followup_question": None, "findings": _EX2_FINDINGS},
    ),
    _step(
        "Confidence Classification",
        {"anomaly": _EX2_ANOMALY, "questionnaire_answers": _EX2_ANSWERS, "findings": _EX2_FINDINGS},
        {"findings": _EX2_SCORED_FINDINGS},
    ),
    _step(
        "Parent Summary",
        {"anomaly": _EX2_ANOMALY, "questionnaire_answers": _EX2_ANSWERS, "findings": _EX2_SCORED_FINDINGS},
        {"parent_summary": _EX2_PARENT_SUMMARY},
    ),
]

AGENT_INFO = {
    "description": (
        "SugarBuddy investigates an abnormal glucose (CGM) event for a parent-teen pair managing "
        "Type 1 diabetes. Given a description of the event, it asks the teen a structured 10 "
        "yes/no question check-in, reasons over the answers together with a curated cause table "
        "and medical reference text (American Diabetes Association / NIDDK), may ask ONE further "
        "self-worded clarifying question if genuinely needed, scores its candidate explanations by "
        "confidence, and returns a short, evidence-based summary for the parent -- a recap of the "
        "event, up to three possible contributing factors each labeled with a confidence level, "
        "and one practical suggestion.\n\nWhat it CAN do: parse a glucose event from plain "
        "language or structured JSON, run the 10-question check-in, ask at most one adaptive "
        "follow-up question, cite which of its sources (the cause table, the medical reference "
        "text, or the teen's own answers) supports each finding, and write its final summary in "
        "Hebrew.\n\nWhat it CANNOT do (constraints): it does not diagnose or replace medical "
        "advice; it does not read a live CGM feed as part of this contract (the event is "
        "described in the prompt, not fetched automatically); and it never asks more than one "
        "follow-up question regardless of how the underlying model responds."
    ),
    "purpose": (
        "Turn a raw glucose anomaly into a calm, evidence-based conversation starter for a "
        "parent-teen pair -- replacing an alarming number with a short list of plausible, "
        "confidence-rated explanations and one concrete next step."
    ),
    "prompt_template": {
        "template": (
            "Turn 1 -- describe the glucose event in plain language or JSON, e.g. 'glucose "
            "spiked to 260 mg/dL and is rising fast'. The agent replies with 10 yes/no "
            "questions.\nTurn 2 -- resend the ENTIRE conversation so far (the agent's last "
            "response followed by your answers) as the new prompt, with your answers as a "
            "numbered list, e.g. '1. Y 2. N 3. Y 4. N 5. Y 6. N 7. N 8. Y 9. Y 10. N'. The agent "
            "either asks one follow-up question or returns the final parent summary.\nTurn 3 "
            "(only if it asked a follow-up) -- resend the whole conversation again with your "
            "answer to that one question."
        ),
        "example": "glucose spiked to 260 mg/dL and is rising fast",
    },
    "prompt_examples": [
        {
            "prompt": "הסוכר קפץ ל-260 ועולה מהר",
            "full_response": _EX1_PARENT_SUMMARY,
            "steps": _EXAMPLE_1_STEPS,
        },
        {
            "prompt": "הסוכר ירד פתאום ל-65 בלי שהבנו למה",
            "full_response": _EX2_PARENT_SUMMARY,
            "steps": _EXAMPLE_2_STEPS,
        },
    ],
}


@app.get("/api/agent_info")
def agent_info():
    return AGENT_INFO


from fastapi import Request
from fastapi.responses import JSONResponse

from agent_pipeline import PipelineClients, run_pipeline
from errors import PipelineError
from llm_client import get_llm_client
from retrieval import get_pinecone_index_safe
from supabase_log import log_execution

_clients: PipelineClients | None = None


def _get_clients() -> PipelineClients:
    global _clients
    if _clients is None:
        llm_client = get_llm_client()
        pinecone_index = get_pinecone_index_safe()
        _clients = PipelineClients(llm_client=llm_client, pinecone_index=pinecone_index, embed_client=llm_client)
    return _clients


@app.post("/api/execute")
async def execute(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"status": "error", "error": "prompt is required", "response": None, "steps": []})

    prompt = body.get("prompt") if isinstance(body, dict) else None

    if not isinstance(prompt, str) or not prompt.strip():
        return JSONResponse({"status": "error", "error": "prompt is required", "response": None, "steps": []})

    try:
        clients = _get_clients()
        result = run_pipeline(prompt, clients)
        response_text = result["response"]
        steps = result["steps"]
    except PipelineError as e:
        return JSONResponse({"status": "error", "error": str(e), "response": None, "steps": []})
    except Exception as e:
        return JSONResponse({"status": "error", "error": f"unexpected error: {e}", "response": None, "steps": []})

    log_execution(prompt, response_text, steps)
    return JSONResponse(
        {"status": "ok", "error": None, "response": response_text, "steps": steps}
    )
