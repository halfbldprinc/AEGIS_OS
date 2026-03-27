from aegis.trust_ledger import TrustLedger


def test_trust_ledger_unlock_policy():
    ledger = TrustLedger()
    category = "liveness"

    assert not ledger.is_unlocked(category)

    for _ in range(49):
        ledger.record_outcome(category, confirmed=True)
    assert not ledger.is_unlocked(category)

    ledger.record_outcome(category, confirmed=True)
    assert ledger.is_unlocked(category)


def test_trust_ledger_rejection_rate_limit():
    ledger = TrustLedger()
    category = "risky"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    for _ in range(3):
        ledger.record_outcome(category, confirmed=False)

    assert not ledger.is_unlocked(category)


def test_trust_ledger_temporary_suspension():
    ledger = TrustLedger()
    category = "suspension"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    ledger.record_outcome(category, confirmed=False)
    assert not ledger.is_unlocked(category)
    ledger.unlock_category(category)
    assert ledger.is_unlocked(category)


def test_trust_ledger_permanent_lockout():
    ledger = TrustLedger()
    category = "hardlock"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    for _ in range(3):
        ledger.record_outcome(category, confirmed=False)

    assert not ledger.is_unlocked(category)
    assert ledger.get_scores(category).permanently_locked


def test_trust_ledger_error_limit():
    ledger = TrustLedger()
    category = "stable"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    for _ in range(5):
        ledger.record_outcome(category, confirmed=False, error=True)

    assert not ledger.is_unlocked(category)


def test_trust_ledger_rejection_rate_exact_threshold():
    ledger = TrustLedger()
    category = "boundary"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    # 5% rejection boundary (2/50 = 4%).
    ledger.record_outcome(category, confirmed=False)
    ledger.record_outcome(category, confirmed=False)

    # Immediately suspended due policy behavior; unlocking should re-evaluate rules.
    assert not ledger.is_unlocked(category)

    ledger.unlock_category(category)
    assert ledger.is_unlocked(category)


def test_trust_ledger_rejection_rate_above_threshold():
    ledger = TrustLedger()
    category = "boundary-fail"

    for _ in range(50):
        ledger.record_outcome(category, confirmed=True)

    # 6% rejection (3/50) should lock by policy (up to temporary suspension / permanent rules).
    for _ in range(3):
        ledger.record_outcome(category, confirmed=False)

    assert not ledger.is_unlocked(category)
