# Reference: EvoAgentX Self-Evolving Architecture

## Core Concepts
EvoAgentX implements a "Self-Evolution Engine" that optimizes agentic workflows through iterative feedback.

### 1. Textual Gradient Descent (TextGrad)
- **Mechanism**: LLM-based backpropagation.
- **Loop**: 
    1. Agent performs task.
    2. Evaluator provides "textual gradient" (critique).
    3. Optimizer LLM updates system prompt based on gradient.

### 2. Evolutionary Prompting (EvoPrompt)
- **Mechanism**: Genetic algorithms applied to prompts.
- **Operations**: Selection, Crossover, Mutation.
- **Goal**: Discovering superior instructions through population-based search.

### 3. Graph Optimization (AFlow)
- **Mechanism**: Modifying the workflow graph structure (adding/removing agent nodes).
- **Technique**: Monte Carlo Tree Search (MCTS) on the workflow topology.

## Applicability to Quant Cockpit
- **Signal Analysis**: Use TextGrad to refine the prompts used by `LobstarAgent` based on trade success/failure.
- **Arbitrage Strategies**: Use EvoPrompt to discover better entry/exit conditions for CLOB arbitrage.
- **Risk Management**: Use automated evaluators to propose "tighter" risk constraints after a drawdown event.

---
Source: Scraped from https://github.com/EvoAgentX/EvoAgentX (May 2026)
