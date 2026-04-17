# Research Protocol

## 12 Methodologies

### 1. Source Hierarchy
Rank sources by reliability. Always prefer higher tiers:
1. **Primary sources** — official docs, RFCs, spec authors
2. **Official channels** — vendor blogs, release notes, changelogs
3. **Practitioner sources** — experienced developers, known experts
4. **Community consensus** — Stack Overflow accepted answers, popular tutorials
5. **AI-generated** — treat as unverified starting points only

### 2. Temporal Awareness
- Check publication dates on every source
- Cross-reference with changelogs and version histories
- Flag anything older than 12 months as potentially stale
- Prefer sources matching the exact version in use

### 3. Negative Space Analysis
- What is NOT being discussed about this topic?
- Missing documentation often signals known pain points
- Absence of complaints may mean nobody uses the feature
- Ask: "What would I expect to find but cannot?"

### 4. Adversarial Thinking
- Actively try to break every proposed approach
- Search for "[technology] problems", "[approach] fails when"
- Consider: what happens at scale? Under load? With bad input?
- If you cannot find failure modes, you have not looked hard enough

### 5. Multi-Source Triangulation
- Require 3+ independent sources before treating a claim as fact
- Independent = different authors, different organizations
- If only one source says it, flag as unverified
- Contradictions between sources are valuable signals

### 6. Upstream Tracing
- Follow every claim to its original source
- Blog cites a paper? Read the paper
- Tutorial references docs? Check the docs say what the tutorial claims
- Stop when you reach the primary source or hit a dead end

### 7. Community Archaeology
- GitHub Issues: search open AND closed issues for the topic
- GitHub Discussions / Wikis: often contain undocumented solutions
- Stack Overflow: read the comments, not just accepted answers
- Discord/Forum archives: real-world usage patterns

### 8. Ecosystem Analysis
- Check package health: download trends, last publish date, open issues count
- Map dependency graph: what does this pull in? What depends on it?
- Look for abandoned maintainers, forked alternatives
- npm audit / pip audit / cargo audit for known vulnerabilities

### 9. Failure Studies
- Search for postmortems involving the technology
- Read anti-pattern documentation
- Find migration guides (they list what went wrong with the old approach)
- "Lessons learned" posts from teams that used it in production

### 10. Comparative Analysis
- Always identify 2-3 alternatives to the proposed approach
- Compare on: maturity, community size, performance, learning curve
- Document WHY the chosen approach wins, not just THAT it does

### 11. Experimental Verification
- Build a minimal reproduction before committing to an approach
- Test the specific version, platform, and configuration in use
- "It works on my machine" is not verification — define the environment
- Time-box experiments: 15 minutes max before reporting findings

### 12. Expert Consultation
- Frame questions with full context (version, environment, goal)
- Ask specific questions, not "how do I do X"
- Provide what you have already tried and what failed
- In roundtable context: this means asking Naomi or a specific worker with domain experience

## When to Stop Researching

- You have 3+ sources agreeing on an approach
- You have identified and addressed the top failure modes
- Diminishing returns: last 3 searches yielded nothing new
- Time budget exceeded (set one before starting)

## Storing Findings

- Key facts go into the roundtable via `speak`
- Persistent discoveries go into the relevant agent's MEMORY.md
- Reusable patterns go into `shared-skills/entries/`

## Anti-Patterns

- Researching instead of building (analysis paralysis)
- Trusting a single source because it is well-written
- Ignoring contradictory evidence because the majority disagrees
- Stopping at the first answer that confirms your assumption
