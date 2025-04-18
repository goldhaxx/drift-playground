# Drift Protocol Developer Playground

Welcome to the Drift Protocol Developer Playground! This repository serves as a comprehensive collection of examples, templates, and composable scripts showcasing various ways to interact with Drift Protocol's developer tools and SDKs.

## Overview

This repository aims to help developers quickly get started with building on top of Drift Protocol by providing:

- Ready-to-use example scripts demonstrating common use cases
- Templates for different types of integrations
- Code samples utilizing various Drift SDKs
- Best practices for interacting with Drift Protocol

Currently, the repository primarily focuses on Python-based implementations using `driftpy`, Drift's official Python SDK. We plan to expand this collection to include examples in other languages and frameworks as they become available.

## Repository Structure

```
drift-playground/
├── python/
│   ├── position-viewer/      # Script to view user positions
│   ├── market-making/        # Market making bot templates
│   └── data-analysis/        # Data analysis and visualization tools
├── typescript/               # (Coming soon)
└── other-languages/         # (Future implementations)
```

## Featured Examples

### Position Viewer
A comprehensive script for viewing all positions for a given authority account on the Drift Protocol. Features include:
- Display of perpetual and spot positions
- Multiple sub-account support
- Detailed account health metrics
- Local data caching to reduce RPC calls

[View Position Viewer Documentation](./python/position-viewer/README.md)

## Getting Started

1. Clone this repository:
   ```bash
   git clone https://github.com/drift-labs/drift-playground.git
   cd drift-playground
   ```

2. Choose an example or template that matches your use case

3. Follow the specific setup instructions in the example's directory

## Prerequisites

Different examples may have different requirements. Generally, you'll need:

- Python 3.7+ for Python examples
- Node.js for TypeScript examples (coming soon)
- A Solana RPC endpoint
- Basic familiarity with Drift Protocol concepts

## Contributing

We welcome contributions! If you have:
- A useful script or template
- An improvement to existing examples
- Ideas for new examples
- Bug fixes or optimizations

Please feel free to:
1. Fork the repository
2. Create a feature branch
3. Submit a pull request

## Resources

- [Drift Protocol Documentation](https://docs.drift.trade/)
- [DriftPy SDK Documentation](https://drift-labs.github.io/driftpy/)
- [Drift Protocol GitHub](https://github.com/drift-labs/protocol-v2)
- [Community Discord](https://discord.com/invite/fMcZBH8ErM)

## License

MIT

---

Note: This repository is under active development. New examples and templates are being added regularly. Watch or star the repository to stay updated with new additions. 