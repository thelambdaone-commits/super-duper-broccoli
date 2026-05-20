from mcp_agents.mcp_server import mcp, _register_specialist_tools

def test_mcp_server_specialist_and_skills_registration():
    """Verifies that all 6 dynamic agent skills and CI reports are successfully registered on FastMCP."""
    # Ensure specialist tools are registered
    _register_specialist_tools(mcp)

    # FastMCP stores registered tools inside _tool_manager._tools
    tools = getattr(mcp, "_tool_manager", None)
    assert tools is not None

    tool_names = list(tools._tools.keys())

    assert "list_ai_specialists" in tool_names
    assert "get_ai_specialist" in tool_names
    assert "get_project_prompt_context" in tool_names
    assert "record_project_memory" in tool_names

    # ── Verify Dynamic Agent Skills are registered ──
    assert "scan_polymarket" in tool_names
    assert "calculate_kelly_size" in tool_names
    assert "run_swarm_backtest" in tool_names
    assert "find_arbitrage_opportunities" in tool_names
    assert "calculate_market_making_spreads" in tool_names
    assert "search_brave_web" in tool_names

    # ── Verify Continuous Improvement is registered ──
    assert "get_continuous_improvement_report" in tool_names

def test_mcp_skills_execution_dispatching():
    """Asserts that calling the wrapper functions dispatches correctly to their respective skills."""
    _register_specialist_tools(mcp)
    tools = mcp._tool_manager._tools

    # Test calculate_kelly_size wrapper execution
    kelly_tool = tools["calculate_kelly_size"]
    res = kelly_tool.fn(
        ticker="ETH",
        side="BUY",
        price=0.45,
        confidence=0.60,
        regime="LOW_VOLATILITY"
    )
    assert res.get("status") == "SUCCESS"
    assert res.get("ticker") == "ETH"
    assert res.get("recommended_size") > 0.0

    # Test scan_polymarket wrapper execution
    scan_tool = tools["scan_polymarket"]
    scan_res = scan_tool.fn(limit=2)
    assert scan_res.get("status") == "SUCCESS"
    assert scan_res.get("limit_scanned") == 2
