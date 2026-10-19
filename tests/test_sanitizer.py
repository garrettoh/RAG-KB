"""Behavioral cases: missing recognizers leak values; broad ones destroy procedures."""

import pytest


@pytest.mark.parametrize(
    "source, expected",
    [
        ("Connect to 192.168.1.20.", "Connect to [REDACTED_IP]."),
        ("ssh 10.0.0.1:2222", "ssh [REDACTED_IP]"),
        ("0.0.0.0 and 255.255.255.255", "[REDACTED_IP] and [REDACTED_IP]"),
        ("2001:db8:0:0:0:0:0:1", "[REDACTED_IP]"),
        ("2001:db8::1", "[REDACTED_IP]"),
        ("::1, :: and fe80::abcd", "[REDACTED_IP], [REDACTED_IP] and [REDACTED_IP]"),
        ("https://[2001:db8::1]:8443/status", "https://[REDACTED_IP]/status"),
        ("fe80::1%eth0", "[REDACTED_IP]"),
        ("[fe80::1%25Ethernet]:443", "[REDACTED_IP]"),
        ("::ffff:192.0.2.1", "[REDACTED_IP]"),
        ("[::ffff:192.0.2.1]:80", "[REDACTED_IP]"),
        ("{\"host\":\"2001:db8::1\",\"backup\":\"10.1.2.3\"}", '{"host":"[REDACTED_IP]","backup":"[REDACTED_IP]"}'),
        ("MAC 00:1A:2b:3C:4d:5E", "MAC [REDACTED_MAC]"),
        ("aa-bb-cc-dd-ee-ff", "[REDACTED_MAC]"),
        ("aabb.ccdd.eeff", "[REDACTED_MAC]"),
        ("password=correct-horse", "password=[REDACTED_PASSWORD]"),
        ("PASSWORD: 'two words'", "PASSWORD: '[REDACTED_PASSWORD]'"),
        ('{"password":"a\\\"b", "enabled":true}', '{"password":"[REDACTED_PASSWORD]", "enabled":true}'),
        ("pwd: hunter2\nnext: keep", "pwd: [REDACTED_PASSWORD]\nnext: keep"),
        ("export DB_PASSWORD=s3cr3t", "export DB_PASSWORD=[REDACTED_PASSWORD]"),
        ("reset --password 'two words' --force", "reset --password '[REDACTED_PASSWORD]' --force"),
        ("reset --passwd=secret --retry 3", "reset --passwd=[REDACTED_PASSWORD] --retry 3"),
        ("api_key=abc123", "api_key=[REDACTED_API_KEY]"),
        ('{"apiKey":"abc123","client_secret":"xyz987"}', '{"apiKey":"[REDACTED_API_KEY]","client_secret":"[REDACTED_API_KEY]"}'),
        ("API key: abc123; retry", "API key: [REDACTED_API_KEY]; retry"),
        ("OPENAI_API_KEY=secret", "OPENAI_API_KEY=[REDACTED_API_KEY]"),
        ("curl --api-key abc123 --url /health", "curl --api-key [REDACTED_API_KEY] --url /health"),
        ("access_token: abc123", "access_token: [REDACTED_API_KEY]"),
        ("Authorization: Bearer abc.def-ghi_jkl=", "Authorization: Bearer [REDACTED_TOKEN]"),
        ("Bearer abc123, then retry", "Bearer [REDACTED_TOKEN], then retry"),
        ("sk-proj-0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("ghp_0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("AKIAIOSFODNN7EXAMPLE", "[REDACTED_API_KEY]"),
        ("xoxb-1234567890-abcdefghijk", "[REDACTED_API_KEY]"),
        ("serial number: ABC-123456", "serial number: [REDACTED_SERIAL]"),
        ('{"serialNumber":"ABCD1234"}', '{"serialNumber":"[REDACTED_SERIAL]"}'),
        ("S/N=ABC123", "S/N=[REDACTED_SERIAL]"),
        ("--serial-number ABC123 --verbose", "--serial-number [REDACTED_SERIAL] --verbose"),
        ("Email jane.doe+alerts@example.co.uk.", "Email [REDACTED_EMAIL]."),
        ("<mailto:help@example.com>", "<mailto:[REDACTED_EMAIL]>"),
        ("https://admin:p%40ss@example.com/path", "https://[REDACTED_CREDENTIALS]@example.com/path"),
        ("https://example.com/?api_key=abc123&view=full", "https://example.com/?api_key=[REDACTED_API_KEY]&view=full"),
        ("https://example.com/?password=abc%26def&token=xyz#help", "https://example.com/?password=[REDACTED_PASSWORD]&token=[REDACTED_API_KEY]#help"),
        ('password=one,api_key=two;serial=ABC123', 'password=[REDACTED_PASSWORD],api_key=[REDACTED_API_KEY];serial=[REDACTED_SERIAL]'),
        ("password:\n  'two words'\nnext: keep", "password:\n  '[REDACTED_PASSWORD]'\nnext: keep"),
        ("password=reset", "password=[REDACTED_PASSWORD]"),
        ("--password reset", "--password [REDACTED_PASSWORD]"),
        ("password: reset", "password: [REDACTED_PASSWORD]"),
        ("password='first\nsecond'\nnext: keep", "password='[REDACTED_PASSWORD]'\nnext: keep"),
        ("password: |\n  first\n  second\nnext: keep", "password: [REDACTED_PASSWORD]\nnext: keep"),
        ("  api_key: >-\n    first\n    second\n  next: keep", "  api_key: [REDACTED_API_KEY]\n  next: keep"),
        ("MAC aa:bb:cc:dd:ee:ff.", "MAC [REDACTED_MAC]."),
        ("Connect to (2001:db8::1).", "Connect to ([REDACTED_IP])."),
        ("https://name@example.com/status", "https://[REDACTED_CREDENTIALS]@example.com/status"),
        ("gho_0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("github_pat_0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("sk-0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("https://x/?client_secret=xyz&ok=1", "https://x/?client_secret=[REDACTED_API_KEY]&ok=1"),
        ("password=abc#secret", "password=[REDACTED_PASSWORD]"),
        ("password=abc&secret", "password=[REDACTED_PASSWORD]"),
        ("password=abc,secret", "password=[REDACTED_PASSWORD]"),
        ("password=#secret", "password=[REDACTED_PASSWORD]"),
        ("password=&secret", "password=[REDACTED_PASSWORD]"),
        ("password=reset-abc123", "password=[REDACTED_PASSWORD]"),
        ("password: reset-abc123 the temporary credential", "password: [REDACTED_PASSWORD] the temporary credential"),
        ("https://x/?password=abc%23secret&token=xyz#help", "https://x/?password=[REDACTED_PASSWORD]&token=[REDACTED_API_KEY]#help"),
    ],
)
def test_redacts_sensitive_values_without_consuming_surroundings(source, expected):
    from app.sanitizer import sanitize_text

    assert sanitize_text(source) == expected
    assert sanitize_text(expected) == expected


@pytest.mark.parametrize(
    "source",
    [
        "", "Upgrade to version 1.2.3, then restart.",
        "Version v1.2.3.4 is documented.", "Invalid hosts 999.1.2.3 and 1.2.3.999.",
        "Run steps 1.2.3.4.5 in order.", "Elapsed 12:30:45; ratio 1:2; error abc:def.",
        "Change the password and rotate the API key.",
        "password: reset it using the portal.", "API key: create one in the dashboard.",
        "Set the serial port to 9600 baud.", "serial: port configuration", "use --password-policy strict",
        "The key to resolution is restarting the service.",
        "Thanks to the logs, restart the service.",
        "Regards the error, apply the patch.",
        "Restart the service.\n\nThanks,\nRestart the router and verify connectivity.",
        "# Resolution\n1. Restart.\n2. Check logs.\n\n```sh\nsystemctl restart app\n```\n",
        "Literal markers [REDACTED_IP] and [REDACTED_PASSWORD].",
        'password=""; api_key=null; serial_number: null',
        "A malformed IPv6 face:b00c and 2001:db8:::1 must remain.",
        "MAC invalid aa:bb:cc:dd:ee:zz stays.",
        "Restart.\n\nRegards,\nJane Doe\n[REDACTED_EMAIL]\n\nThe next step is to check logs.",
        "```text\nSent from my iPhone\nThanks,\nJane Doe\n```",
    ],
)
def test_preserves_procedures_and_non_sensitive_content(source):
    from app.sanitizer import sanitize_text

    assert sanitize_text(source) == source


@pytest.mark.parametrize(
    "signature",
    [
        "-- \nJane Doe\nSupport Engineer\njane@example.com\n+1 (555) 123-4567",
        "Kind regards,\nJane Doe\nSupport Engineer\njane@example.com",
        "Best regards,\nJane Doe\nExample Company\nEmail: jane@example.com\nPhone: 555-123-4567",
        "Thanks,\nJane Doe\njane@example.com",
    ],
)
def test_removes_contact_signature_but_retains_resolution(signature):
    from app.sanitizer import sanitize_text

    assert sanitize_text("Restart the service.\n\n" + signature) == "Restart the service.\n\n[REDACTED_SIGNATURE]"


def test_mobile_footer_does_not_remove_following_instructions():
    from app.sanitizer import sanitize_text

    assert sanitize_text("Restart.\nSent from my iPhone\n\n2. Verify logs.") == "Restart.\n[REDACTED_SIGNATURE]\n\n2. Verify logs."


def test_confidentiality_footer_removes_only_its_paragraph():
    from app.sanitizer import sanitize_text

    source = "Restart.\n\nThis email and any attachments are confidential.\nIf received in error, delete it.\n\n2. Verify logs."
    assert sanitize_text(source) == "Restart.\n\n[REDACTED_SIGNATURE]\n\n2. Verify logs."


def test_signature_does_not_consume_a_following_procedure_paragraph():
    from app.sanitizer import sanitize_text

    source = "Restart.\n\nRegards,\nJane Doe\njane@example.com\n\nThe next step is to check logs."
    assert sanitize_text(source) == "Restart.\n\nRegards,\nJane Doe\n[REDACTED_EMAIL]\n\nThe next step is to check logs."


def test_signature_does_not_consume_a_short_capitalized_instruction():
    from app.sanitizer import sanitize_text

    source = "Restart.\n\nThanks,\nJane Doe\njane@example.com\nSave the configuration"
    assert sanitize_text(source) == "Restart.\n\nThanks,\nJane Doe\n[REDACTED_EMAIL]\nSave the configuration"


def test_preserves_crlf_structure_around_redactions():
    from app.sanitizer import sanitize_text

    assert sanitize_text("1. Run:\r\npassword=secret\r\n2. Verify.\r\n") == "1. Run:\r\npassword=[REDACTED_PASSWORD]\r\n2. Verify.\r\n"


@pytest.mark.parametrize("value", ["S3cr3t;tail", "S3cr3t)tail", "S3cr3t]tail", "S3cr3t`tail", "S3cr3t#tail"])
@pytest.mark.parametrize("label, marker", [("password", "PASSWORD"), ("api_key", "API_KEY"), ("serial", "SERIAL")])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_yaml_plain_scalar_punctuation_is_part_of_the_sensitive_value(value, label, marker, newline):
    from app.sanitizer import sanitize_text

    source = f"```yaml{newline}  {label}: {value} # keep this comment{newline}  enabled: true{newline}```"
    expected = f"```yaml{newline}  {label}: [REDACTED_{marker}] # keep this comment{newline}  enabled: true{newline}```"
    assert sanitize_text(source) == expected
    assert sanitize_text(expected) == expected
    assert sanitize_text(f"{label}: {value}") == f"{label}: [REDACTED_{marker}]"


@pytest.mark.parametrize("source", ["password: # comment only", "api_key: # configure separately", "password: reset it using the portal."])
def test_yaml_comment_or_instruction_is_not_a_credential(source):
    from app.sanitizer import sanitize_text

    assert sanitize_text(source) == source


@pytest.mark.parametrize(
    "value, expected",
    [
        ("10.1.2.3", "[REDACTED_IP]"), ("[2001:db8::1]:443", "[REDACTED_IP]"),
        ("aa:bb:cc:dd:ee:ff", "[REDACTED_MAC]"),
        ("password=secret", "password=[REDACTED_PASSWORD]"),
        ("api_key=secret", "api_key=[REDACTED_API_KEY]"),
        ("Bearer secret", "Bearer [REDACTED_TOKEN]"),
        ("serial=ABC123", "serial=[REDACTED_SERIAL]"),
        ("jane@example.com", "[REDACTED_EMAIL]"),
        ("ghp_0123456789abcdefghijklmnop", "[REDACTED_API_KEY]"),
        ("https://admin:secret@example.com/", "https://[REDACTED_CREDENTIALS]@example.com/"),
    ],
)
def test_redacts_inside_code_fences_without_discarding_code(value, expected):
    from app.sanitizer import sanitize_text

    assert sanitize_text(f"1. Run:\n```text\n{value}\n```\n2. Verify.") == f"1. Run:\n```text\n{expected}\n```\n2. Verify."


@pytest.mark.parametrize(
    "source",
    [
        "password=secret api_key=abc serial=ABC123 host=10.1.2.3",
        '{"password":"a b","token":"abc", "email":"jane@example.com"}',
        "```sh\ncurl https://u:p@[::1]:443/?api_key=abc\n```",
        "Restart.\n\nRegards,\nJane Doe\njane@example.com",
        "[REDACTED_IP] [REDACTED_PASSWORD] [REDACTED_API_KEY] [REDACTED_SERIAL]",
    ],
)
def test_redaction_is_idempotent(source):
    from app.sanitizer import sanitize_text

    once = sanitize_text(source)
    assert sanitize_text(once) == once
