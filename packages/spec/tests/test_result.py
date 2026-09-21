from spec.core.result import CheckResult, CheckStatus, VerificationReport


def test_incomplete_required_check_prevents_global_pass() -> None:
    report = VerificationReport(
        checks=(
            CheckResult(id="lint", status=CheckStatus.PASS, required=True),
            CheckResult(id="tests", status=CheckStatus.INCOMPLETE, required=True),
        )
    )

    assert report.status is CheckStatus.INCOMPLETE
    assert report.passed is False


def test_explicitly_skipped_optional_check_does_not_fail_report() -> None:
    report = VerificationReport(
        checks=(
            CheckResult(id="tests", status=CheckStatus.PASS, required=True),
            CheckResult(id="typing", status=CheckStatus.SKIPPED, required=False),
        )
    )

    assert report.status is CheckStatus.PASS
    assert report.passed is True


def test_report_without_required_checks_is_incomplete() -> None:
    report = VerificationReport(
        checks=(CheckResult(id="advisory", status=CheckStatus.PASS, required=False),)
    )

    assert report.status is CheckStatus.INCOMPLETE
    assert report.passed is False


def test_report_falls_back_to_incomplete_for_an_unrecognized_status() -> None:
    # CheckStatus is a closed enum, so every real status is already handled by the
    # explicit branches above. This exercises the defensive fallback by forcing a
    # status value outside that enum, which the dataclass does not validate at runtime.
    report = VerificationReport(
        checks=(CheckResult(id="unknown", status="WEIRD", required=True),)  # type: ignore[arg-type]
    )

    assert report.status is CheckStatus.INCOMPLETE
    assert report.passed is False
