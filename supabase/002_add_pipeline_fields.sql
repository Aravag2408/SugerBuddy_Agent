alter table execution_log
    add column if not exists stage text,
    add column if not exists anomaly jsonb,
    add column if not exists questionnaire_answers jsonb,
    add column if not exists notes text,
    add column if not exists retrieved_context jsonb,
    add column if not exists react_findings jsonb,
    add column if not exists need_more_info boolean,
    add column if not exists confidence_result jsonb,
    add column if not exists parent_summary text,
    add column if not exists followup_question text,
    add column if not exists followup_answer text;
