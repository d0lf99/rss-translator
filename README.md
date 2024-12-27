# RSS Translator Bot

A Telegram bot that monitors a FreshRSS instance for new articles, translates them to English using DeepL, and forwards them to a specified Telegram channel. Each article is formatted with an underlined title and a source attribution link.

## Features

- 🔄 Real-time RSS feed monitoring via FreshRSS API
- 🌐 Automatic translation to English using DeepL
- 📝 Clean HTML formatting for Telegram compatibility
- 🔗 Source attribution with clickable links
- 🚫 Duplicate prevention via in-memory tracking
- 📋 Configurable logging levels

## Requirements

- Docker and Docker Compose
- FreshRSS instance with API access
- DeepL API key
- Telegram Bot token and chat ID

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/rss-translator.git
cd rss-translator
```

2. Create a `docker-compose.yml` file with your configuration:
```yaml
services:
  rss-translator:
    build: .
    container_name: rss-translator
    restart: unless-stopped
    environment:
      - FRESHRSS_URL=https://your-freshrss-instance.com
      - FRESHRSS_USER=your_username
      - FRESHRSS_PASSWORD=your_password
      - DEEPL_API_KEY=your-deepl-api-key
      - TELEGRAM_BOT_TOKEN=your-telegram-bot-token
      - TELEGRAM_CHAT_ID=your-telegram-chat-id
      - TZ=Europe/Rome
      - LOG_LEVEL=INFO
    volumes:
      - ./logs:/app/logs
```

3. Start the bot:
```bash
docker-compose up -d
```

## Configuration

### Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `FRESHRSS_URL` | Your FreshRSS instance URL | Yes |
| `FRESHRSS_USER` | FreshRSS username | Yes |
| `FRESHRSS_PASSWORD` | FreshRSS password | Yes |
| `DEEPL_API_KEY` | DeepL API key for translation | Yes |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | Yes |
| `TELEGRAM_CHAT_ID` | Target Telegram chat/channel ID | Yes |
| `TZ` | Timezone for logs (default: UTC) | No |
| `LOG_LEVEL` | Logging verbosity (default: INFO) | No |

### Logging Levels

The bot's logging verbosity can be controlled via the `LOG_LEVEL` environment variable:

- `DEBUG`: Most verbose, logs everything including detailed debugging information
- `INFO`: Regular operation logs (default)
- `WARNING`: Only potential issues and warnings
- `ERROR`: Only error messages
- `CRITICAL`: Only critical failures

### Message Format

Articles are formatted in Telegram as:
```
<underlined>Translated Title</underlined>

Translated content...

via Source Name (as clickable link)
```

## Data Storage

The bot maintains rotating log files in the `./logs` directory. Article read state is tracked in memory during runtime.

## Maintenance

### Viewing Logs
```bash
docker-compose logs -f rss-translator
```

### Updating
```bash
docker-compose pull
docker-compose up -d
```

### Stopping
```bash
docker-compose down
```

## Limitations

- Maximum message length of 500 characters (configurable)
- Translations are one-way to English
- One FreshRSS instance per bot
- One target Telegram chat/channel per bot
- Read state tracking is reset on bot restart

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- [FreshRSS](https://freshrss.org/) for the RSS aggregation
- [DeepL](https://www.deepl.com/) for translation services
- [python-telegram-bot](https://python-telegram-bot.org/) for Telegram integration

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.