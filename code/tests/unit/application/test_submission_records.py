"""Submission field-exposure semantics independent of dataset I/O."""

from ghost_audit.application.submission.records import SubmissionRecords


def test_stable_reference_is_permitted_for_redaction_not_anonymization():
    direct, stable, subject = SubmissionRecords._exposure(
        {
            "customer_reference": "user_26",
            "requester_email": None,
            "message_excerpt": "Order update.",
        },
        {"user_26", "subject@example.test"},
    )
    assert (direct, stable, subject) == (False, True, False)
    _, _, subject = SubmissionRecords._exposure(
        {"message_text": "Send it to SUBJECT@example.test please"},
        {"user_26", "subject@example.test"},
    )
    assert subject
