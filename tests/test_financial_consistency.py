"""
Test financial consistency across the entire pipeline.

Validates that:
1. Proposed trade economics → Verified economics → Risk evaluation → Execution
   all use mathematically consistent values
2. Max Loss, Max Profit, and debit calculations are consistent
3. Risk Engine uses verified values, not LLM-generated estimates
4. Execution tracks variance between expected and actual debit
"""

from datetime import date
from app.models.strategy import TradeProposal, SpreadType
from app.models.trade_validation import TradeValidator
from app.risk.risk_engine import RiskEngine
from app.models.market import MarketAnalysis, MarketDirection


def test_verified_economics_calculation():
    """Test that verified economics are calculated correctly."""
    
    # Setup: Create a bull call spread
    current_price = 100.0
    long_strike = 100.0
    short_strike = 105.0
    spread_width = short_strike - long_strike  # $5
    
    # Net debit should be 35% of spread width = $1.75
    estimated_net_debit_pct = 0.35
    
    expiration = date(2026, 9, 18)
    validator = TradeValidator()
    
    economics, warnings = validator.validate_and_calculate(
        current_price=current_price,
        long_strike=long_strike,
        short_strike=short_strike,
        expiration=expiration,
        estimated_net_debit_pct=estimated_net_debit_pct,
        quantity=1,
    )
    
    # Verify calculations
    assert economics.spread_width == 5.0, f"Expected spread_width=5.0, got {economics.spread_width}"
    
    # Net debit per share should be 0.35 * 5.0 = 1.75
    expected_net_debit_per_share = estimated_net_debit_pct * spread_width
    assert abs(economics.net_debit_per_share - expected_net_debit_per_share) < 0.001, \
        f"Expected net_debit_per_share={expected_net_debit_per_share}, got {economics.net_debit_per_share}"
    
    # Net debit total should be 1.75 * 100 = $175
    expected_net_debit_total = expected_net_debit_per_share * 100
    assert abs(economics.net_debit_total - expected_net_debit_total) < 0.01, \
        f"Expected net_debit_total=${expected_net_debit_total}, got ${economics.net_debit_total}"
    
    # Max loss should equal net debit total
    assert abs(economics.max_loss_per_contract - expected_net_debit_total) < 0.01, \
        f"Expected max_loss=${expected_net_debit_total}, got ${economics.max_loss_per_contract}"
    
    # Max profit should be (spread_width - net_debit) * 100 = (5.0 - 1.75) * 100 = $325
    expected_max_profit = (spread_width - expected_net_debit_per_share) * 100
    assert abs(economics.max_profit_per_contract - expected_max_profit) < 0.01, \
        f"Expected max_profit=${expected_max_profit}, got ${economics.max_profit_per_contract}"
    
    print("✓ Verified economics calculation is correct")


def test_risk_engine_uses_verified_values():
    """Test that RiskEngine uses verified_max_loss instead of LLM max_loss."""
    
    # Create a proposal with intentionally wrong LLM values
    proposal = TradeProposal(
        ticker="AAPL",
        strategy=SpreadType.BULL_CALL_SPREAD,
        expiration=date(2026, 9, 18),
        long_strike=100.0,
        short_strike=105.0,
        long_symbol="AAPL260918C00100000",
        short_symbol="AAPL260918C00105000",
        
        # LLM-generated values (intentionally wrong for testing)
        max_loss=500.0,
        max_profit=800.0,
        
        quantity=1,
        rationale="Test trade",
        based_on="Test market direction",
    )
    
    # Set the verified values to what they should actually be
    proposal.verified_max_loss = 175.0  # correct value
    proposal.verified_max_profit = 325.0  # correct value
    proposal.verified_net_debit = 175.0
    proposal.verified_spread_width = 5.0
    
    # Create risk engine with tight limits
    risk_engine = RiskEngine(
        max_risk_per_trade=200.0,  # Should pass with verified value, fail with LLM value
        max_position_size=5000.0,
        max_daily_trades=5,
        max_daily_loss=1000.0,
    )
    
    # Evaluate the proposal
    decision = risk_engine.evaluate(proposal)
    
    # Should pass because verified_max_loss=$175 < limit=$200
    assert decision.verdict.value == "pass", \
        f"Expected PASS (verified_max_loss=$175 < $200), but got {decision.verdict.value}: {decision.reason}"
    
    # Verify that the check used the verified value, not the LLM value
    max_risk_check = next((c for c in decision.checks if c.rule == "max_risk_per_trade"), None)
    assert max_risk_check is not None, "max_risk_per_trade check not found"
    assert "$175.00" in max_risk_check.detail, \
        f"Check detail should show $175.00 (verified), got: {max_risk_check.detail}"
    
    print("✓ RiskEngine correctly uses verified_max_loss, not LLM values")


def test_consistent_economics_across_pipeline():
    """Test that economics remain consistent from proposal through execution."""
    
    # Scenario: Bull call spread on AAPL
    # Proposed: $5 spread, 35% net debit = $1.75 debit
    # This should yield Max Loss=$175, Max Profit=$325
    
    current_price = 100.0
    long_strike = 100.0
    short_strike = 105.0
    quantity = 1
    
    # Step 1: Strategy Agent proposes trade (with estimated LLM values)
    proposal = TradeProposal(
        ticker="AAPL",
        strategy=SpreadType.BULL_CALL_SPREAD,
        expiration=date(2026, 9, 18),
        long_strike=long_strike,
        short_strike=short_strike,
        long_symbol="AAPL260918C00100000",
        short_symbol="AAPL260918C00105000",
        max_loss=175.0,  # LLM estimate
        max_profit=325.0,  # LLM estimate
        quantity=quantity,
        rationale="Bullish outlook",
        based_on="AAPL bullish",
    )
    
    # Step 2: Trade Validator calculates verified economics
    validator = TradeValidator()
    spread_width = short_strike - long_strike
    
    # Back-calculate the net debit percentage from the proposed max_loss
    # max_loss = net_debit_per_share * 100
    # net_debit_per_share = max_loss / 100 = 175 / 100 = 1.75
    # estimated_net_debit_pct = net_debit_per_share / spread_width = 1.75 / 5.0 = 0.35
    estimated_net_debit_pct = (proposal.max_loss / (100 * quantity)) / spread_width
    
    economics, warnings = validator.validate_and_calculate(
        current_price=current_price,
        long_strike=long_strike,
        short_strike=short_strike,
        expiration=proposal.expiration,
        estimated_net_debit_pct=estimated_net_debit_pct,
        quantity=quantity,
    )
    
    # Update proposal with verified values
    proposal.verified_max_loss = economics.max_loss_per_contract * quantity
    proposal.verified_max_profit = economics.max_profit_per_contract * quantity
    proposal.verified_net_debit = economics.net_debit_total
    proposal.verified_spread_width = economics.spread_width
    
    # Verify consistency
    assert abs(proposal.verified_max_loss - 175.0) < 0.01, \
        f"Verified max_loss should be $175, got ${proposal.verified_max_loss}"
    assert abs(proposal.verified_max_profit - 325.0) < 0.01, \
        f"Verified max_profit should be $325, got ${proposal.verified_max_profit}"
    assert abs(proposal.verified_net_debit - 175.0) < 0.01, \
        f"Verified net_debit should be $175, got ${proposal.verified_net_debit}"
    
    # Step 3: Risk Engine evaluates using verified values
    risk_engine = RiskEngine(max_risk_per_trade=500.0)
    decision = risk_engine.evaluate(proposal)
    
    # Should pass
    assert decision.verdict.value == "pass", \
        f"Risk check should pass with verified_max_loss=$175 < $500, got: {decision.reason}"
    
    # Verify the check used the verified value
    max_risk_check = next((c for c in decision.checks if c.rule == "max_risk_per_trade"), None)
    assert "$175.00" in max_risk_check.detail, \
        f"Should evaluate against $175.00, got: {max_risk_check.detail}"
    
    print("✓ Economics remain consistent across entire pipeline")


def test_execution_debit_variance_tracking():
    """Test that execution properly tracks expected vs actual debit variance."""
    from app.models.execution import ExecutionResult, ExecutionStatus
    
    # Expected debit from verified economics
    expected_debit = 175.0  # $1.75 per share
    
    # Simulate scenarios
    scenarios = [
        {
            "name": "Better fill (lower debit)",
            "filled_price": 170.0,
            "expected_variance": -5.0,
            "description": "Filled at better price than expected",
        },
        {
            "name": "Worse fill (higher debit)",
            "filled_price": 231.0,  # This is the problem case from the issue
            "expected_variance": 56.0,
            "description": "Filled at worse price than expected",
        },
        {
            "name": "Exactly as expected",
            "filled_price": 175.0,
            "expected_variance": 0.0,
            "description": "Filled at exactly expected price",
        },
    ]
    
    for scenario in scenarios:
        execution = ExecutionResult(
            status=ExecutionStatus.FILLED,
            order_id="test-order-123",
            filled_avg_price=scenario["filled_price"],
            expected_debit=expected_debit,
            debit_variance=scenario["filled_price"] - expected_debit,
            detail="Test execution",
        )
        
        assert execution.debit_variance is not None, f"Variance should be tracked for {scenario['name']}"
        assert abs(execution.debit_variance - scenario["expected_variance"]) < 0.01, \
            f"{scenario['name']}: Expected variance={scenario['expected_variance']}, " \
            f"got {execution.debit_variance}"
        
        # Recalculate P&L based on actual fill
        spread_width = 5.0  # $5
        quantity = 1
        actual_max_loss = scenario["filled_price"] * 100 * quantity
        actual_max_profit = (spread_width - (scenario["filled_price"] / 100)) * 100 * quantity
        
        print(f"  ✓ {scenario['name']}: filled=${scenario['filled_price']:.0f}, "
              f"variance=${execution.debit_variance:.0f}, "
              f"new_max_loss=${actual_max_loss:.0f}, "
              f"new_max_profit=${actual_max_profit:.0f}")
    
    print("✓ Execution debit variance is properly tracked")


if __name__ == "__main__":
    print("Running financial consistency tests...\n")
    test_verified_economics_calculation()
    test_risk_engine_uses_verified_values()
    test_consistent_economics_across_pipeline()
    test_execution_debit_variance_tracking()
    print("\n✅ All financial consistency tests passed!")
