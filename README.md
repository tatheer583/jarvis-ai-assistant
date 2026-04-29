
<p align="center">
  <img src="https://img.shields.io/github/stars/tatheer583/jarvis-ai-assistant?style=social" alt="GitHub stars">
  <img src="https://img.shields.io/github/forks/tatheer583/jarvis-ai-assistant?style=social" alt="GitHub forks">
  <img src="https://img.shields.io/github/license/tatheer583/jarvis-ai-assistant" alt="License">
  <img src="https://img.shields.io/badge/Python-3.8%2B-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/tatheer583/jarvis-ai-assistant/main/Data/jarvis_banner.png" alt="Jarvis AI Banner" width="600">
</p>

# Jarvis AI Assistant

A comprehensive, AI-powered personal assistant framework designed to streamline workflows through intelligent automation, natural language processing, and multi-modal interactions.

## Overview

Jarvis integrates cutting-edge AI technologies to provide a unified platform for conversational AI, content generation, real-time information retrieval, browser automation, and speech processing. Built with a modular architecture for extensibility and maintainability.

## Key Features

- **Conversational AI**: Intelligent chatbot powered by advanced language models with context-aware responses
- **Generative AI**: AI-driven image generation from textual descriptions
- **Voice Processing**: 
  - Speech-to-Text: Convert audio input to text with high accuracy
  - Text-to-Speech: Natural-sounding speech synthesis
- **Web Intelligence**: Real-time search engine integration for current information retrieval
- **Browser Automation**: Automate complex web-based workflows and interactions
- **Remote Access**: Secure remote control capabilities for distributed operations
- **Multi-Language Support**: Seamless language detection and switching
- **Task Automation**: General-purpose automation engine for repetitive tasks

## Project Structure

```
Jarvis/
├── Backend/           # Core business logic and API implementations
├── Frontend/          # User interface and visualization components
├── Data/              # Configuration and data storage
├── Main.py            # Application entry point
├── Requirements.txt   # Python dependencies
└── README.md          # Project documentation
```

## Installation

### Prerequisites
- Python 3.8 or higher
- pip (Python package manager)
- Chrome/Chromium browser (for browser automation features)
- Microphone access (for speech-to-text functionality)

### Setup Steps

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd Jarvis
   ```

2. Create and activate a virtual environment (recommended):
   ```bash
   python -m venv .venv
   .venv\Scripts\activate  # On Windows
   # or
   source .venv/bin/activate  # On macOS/Linux
   ```

3. Install dependencies:
   ```bash
   pip install -r Requirements.txt
   ```

## Getting Started

### Running the Application
- **GUI Mode** (Recommended for most users):
  ```bash
  python Frontend/GUI.py
  ```

- **CLI Mode** (For developers and automation):
  ```bash
  python Main.py
  ```

### Using Specific Modules
Each backend module can be imported and used independently:
```python
from Backend.Chatbot import Chatbot
from Backend.ImageGenration import ImageGenerator
from Backend.SpeechToText import SpeechToText
```

## Configuration

- Review configuration files in the `Data/` directory
- Update language preferences in `Backend/LanguageManager.py`
- Customize automation rules in `Backend/Automation.py`

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Missing dependencies | Run `pip install -r Requirements.txt` and verify installation |
| Python version error | Ensure Python 3.8+ is installed: `python --version` |
| Browser automation fails | Install Chrome/Chromium and verify `chromedriver` compatibility |
| Speech features unavailable | Check microphone/speaker connectivity and permissions |
| Port conflicts | Modify port settings in configuration files if running remote access |

## Development

### Running Tests
```bash
python debug_groq.py
```

### Code Quality
- Follow PEP 8 style guidelines
- Include docstrings for all functions
- Test new features before submission

## Contributing

Contributions are welcome! Please:
1. Fork the repository
2. Create a feature branch (`git checkout -b feature/improvement`)
3. Commit your changes (`git commit -am 'Add improvement'`)
4. Push to the branch (`git push origin feature/improvement`)
5. Submit a Pull Request

## License

[Add your license information here]

## Support

For issues, feature requests, or questions:
- Open an issue on the GitHub repository
- Check existing documentation in the `Data/` directory