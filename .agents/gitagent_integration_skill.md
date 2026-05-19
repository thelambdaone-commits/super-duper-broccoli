# GitAgent Integration Skill

## Purpose
GitAgent is a specialized AI agent for automating Git workflows, PR management, and collaborative development. This skill integrates GitAgent into Lobstar to automate code review, branch management, and PR operations.

## Triggers
- `/git review` - Automated PR code review
- `/git analyze` - Analyze commit history
- `/git suggest` - Suggest improvements
- `/agent gitagent` - Direct GitAgent invocation

## Integration Points
- **Location**: `agents/gitagent/`
- **Type**: TypeScript/Node.js agent
- **Skills**: `agents/gitagent/skills/`
- **Agents**: `agents/gitagent/agents/`

## Execution Steps
1. Load GitAgent environment from `agents/gitagent/.env`
2. Parse Git repository context
3. Execute requested skill (review, analyze, suggest)
4. Return structured output to Lobstar
5. Log operations to memory

## Behavioral Boundaries & Constraints
- **No force-pushes**: Prevent destructive Git operations
- **Branch protection**: Cannot modify protected branches
- **Review-only**: Code reviews are suggestions, not enforcement
- **Audit trail**: All operations logged in `agents/gitagent/memory/`
- **Rate limiting**: Respect GitHub API limits (60/min for authenticated, 10/min for unauthenticated)

## Dependencies
- Node.js >= 18
- Git >= 2.30
- GitHub CLI optional but recommended

## Configuration
```bash
# Initialize GitAgent
cd agents/gitagent
npm install
cp .env.example .env  # Configure GitHub token
```

## Usage Examples
```javascript
// Import and use GitAgent within Lobstar agents
const GitAgent = require('./agents/gitagent/src');

// Run a code review
await GitAgent.review({
  repo: 'origin',
  pr: 42
});

// Analyze commit history
await GitAgent.analyze({
  depth: 10
});
```
