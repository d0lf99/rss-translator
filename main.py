from dataclasses import dataclass
from typing import Optional, List, Dict, Any
import os
import asyncio
import logging
import aiohttp
import deepl
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pythonjsonlogger import jsonlogger
from telegram import Bot
from telegram.ext import Application, ContextTypes

# Constants
MAX_MESSAGE_LENGTH = 500
LOG_ROTATION_SIZE = 5 * 1024 * 1024  # 5MB
LOG_BACKUP_COUNT = 3
FEED_CHECK_INTERVAL = 60  # seconds
MAX_TELEGRAM_MESSAGE_LENGTH = 4096
HTML_REPLACEMENTS = [
    ('<figure>', ''),
    ('</figure>', '\n'),
    ('<p>', ''),
    ('</p>', '\n\n'),
    ('<br>', '\n'),
    ('<br/>', '\n'),
    ('<br />', '\n'),
    ('<div>', ''),
    ('</div>', '\n'),
]
ALLOWED_HTML_TAGS = {'b', 'strong', 'i', 'em', 'u', 's', 'a', 'code', 'pre'}
ARTICLES_PER_FETCH = 50

@dataclass
class Config:
    """Configuration settings loaded from environment variables"""
    freshrss_url: str
    freshrss_user: str
    freshrss_password: str
    telegram_token: str
    telegram_chat_id: str
    deepl_api_key: str
    log_level: str = 'INFO'
    
    @classmethod
    def from_env(cls) -> 'Config':
        """Load configuration from environment variables"""
        return cls(
            freshrss_url=os.getenv('FRESHRSS_URL', ''),
            freshrss_user=os.getenv('FRESHRSS_USER', ''),
            freshrss_password=os.getenv('FRESHRSS_PASSWORD', ''),
            telegram_token=os.getenv('TELEGRAM_BOT_TOKEN', ''),
            telegram_chat_id=os.getenv('TELEGRAM_CHAT_ID', ''),
            deepl_api_key=os.getenv('DEEPL_API_KEY', ''),
            log_level=os.getenv('LOG_LEVEL', 'INFO')
        )

@dataclass
class Article:
    """Article data structure"""
    id: str          # Full ID
    guid: str        # Short ID
    title: str
    content: str
    link: str
    source_title: str

def setup_logging(log_level: str) -> logging.Logger:
    """Configure logging with specified level"""
    valid_levels = {
        'DEBUG': logging.DEBUG,
        'INFO': logging.INFO,
        'WARNING': logging.WARNING,
        'ERROR': logging.ERROR,
        'CRITICAL': logging.CRITICAL
    }
    level = valid_levels.get(log_level.upper(), logging.INFO)
    
    os.makedirs('logs', exist_ok=True)

    logger = logging.getLogger('rss_translator')
    logger.setLevel(level)

    file_handler = RotatingFileHandler(
        'logs/rss_translator.log',
        maxBytes=LOG_ROTATION_SIZE,
        backupCount=LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(
        jsonlogger.JsonFormatter('%(asctime)s %(levelname)s %(message)s')
    )
    file_handler.setLevel(level)
    logger.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(level)
    console_handler.setFormatter(
        logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    )
    logger.addHandler(console_handler)

    logger.info(f"Logging initialized at {log_level} level")
    return logger

class RSSTranslator:
    def __init__(self, config: Config):
        """Initialize RSS Translator with configuration"""
        self.config = config
        self.session: Optional[aiohttp.ClientSession] = None
        self.deepl = deepl.Translator(config.deepl_api_key)
        self.is_running = True
        self.auth_token: Optional[str] = None
        self.marked_as_read = set()
        logger.info("RSSTranslator initialized")

    async def get_session(self):
        """Async context manager for aiohttp session"""
        if not self.session:
            self.session = aiohttp.ClientSession()
            logger.info("Initialized aiohttp session")
        return self.session

    async def close_session(self) -> None:
        """Close aiohttp session if it exists"""
        if self.session:
            await self.session.close()
            self.session = None
            logger.info("Closed aiohttp session")

    def clean_html(self, content: str) -> str:
        """Clean HTML content for Telegram compatibility"""
        try:
            # Replace common HTML structures
            for old, new in HTML_REPLACEMENTS:
                content = content.replace(old, new)

            # Keep only allowed formatting tags
            current_pos = 0
            result = []

            while True:
                tag_start = content.find('<', current_pos)
                if tag_start == -1:
                    result.append(content[current_pos:])
                    break

                result.append(content[current_pos:tag_start])

                tag_end = content.find('>', tag_start)
                if tag_end == -1:
                    result.append(content[tag_start:])
                    break

                tag = content[tag_start+1:tag_end]
                if tag.startswith('/'):
                    tag = tag[1:]
                if ' ' in tag:
                    tag = tag.split()[0]

                if tag.lower() in ALLOWED_HTML_TAGS:
                    result.append(content[tag_start:tag_end+1])

                current_pos = tag_end + 1

            cleaned = ''.join(result)

            # Remove excessive newlines
            while '\n\n\n' in cleaned:
                cleaned = cleaned.replace('\n\n\n', '\n\n')

            return cleaned.strip()
        except Exception as e:
            logger.error(f"HTML cleaning error: {e}")
            return content.replace('<', '&lt;').replace('>', '&gt;')  # Fallback: escape all HTML

    def truncate_content(self, content: str, max_length: int) -> str:
        """Truncate content to specified length at sentence boundary"""
        if len(content) <= max_length:
            return content

        end_pos = max(
            content.rfind('.', 0, max_length),
            content.rfind('!', 0, max_length),
            content.rfind('?', 0, max_length)
        )
        
        return content[:end_pos + 1] + "..." if end_pos != -1 else content[:max_length] + "..."

    async def translate_text(self, text: str) -> str:
        """Translate text to English using DeepL"""
        try:
            result = self.deepl.translate_text(text, target_lang="EN-US")
            return result.text
        except Exception as e:
            logger.error(f"Translation error: {e}")
            return text

    async def send_telegram_message(self, message: str, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Send formatted message to Telegram"""
        try:
            if len(message) > MAX_TELEGRAM_MESSAGE_LENGTH:
                message = message[:MAX_TELEGRAM_MESSAGE_LENGTH-3] + "..."
            
            await context.bot.send_message(
                chat_id=self.config.telegram_chat_id,
                text=message,
                parse_mode='HTML',
                disable_web_page_preview=True
            )
            logger.debug("Sent message to Telegram")
        except Exception as e:
            logger.error(f"Telegram error: {e}")

    async def mark_as_read(self, article_id: str) -> bool:
        """Mark article as read in FreshRSS"""
        if article_id in self.marked_as_read:  # Add this check
            logger.debug(f"Article {article_id} already marked as read")
            return True

        session = await self.get_session()
        try:
            url = f"{self.config.freshrss_url}/api/greader.php/reader/api/0/edit-tag"
            headers = {"Authorization": f"GoogleLogin auth={self.auth_token}"}
            params = {
                'i': article_id,
                'a': 'user/-/state/com.google/read',
                'ac': 'edit',
                's': 'user/-/state/com.google/reading-list'
            }

            async with session.post(url, headers=headers, params=params) as response:
                response_text = await response.text()
                logger.debug(f"Mark as read response for {article_id}: {response.status} - {response_text}")
                
                if response.status != 200 or response_text.strip() != 'OK':
                    logger.error(f"Failed to mark article as read: {response.status}")
                    return False

                self.marked_as_read.add(article_id)  # Add this line
                return True
                
        except Exception as e:
            logger.error(f"Error marking article as read: {e}")
            return False
            
    async def process_article(self, article: Article, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Process single article: translate, format, and send"""
        try:
            cleaned_content = self.clean_html(article.content)

            # Translate content
            try:
                translated_title = await self.translate_text(article.title)
                translated_content = await self.translate_text(cleaned_content)
                logger.debug(f"Translated title: {translated_title}")
            except Exception as e:
                logger.error(f"Translation error: {e}")
                translated_title = article.title
                translated_content = cleaned_content

            # Format and send message
            truncated_content = self.truncate_content(translated_content, MAX_MESSAGE_LENGTH)
            message = (
                f"<u>{translated_title}</u>\n\n"
                f"{truncated_content}\n\n"
                f"via <a href='{article.link}'>{article.source_title}</a>"
            )

            # Send message and mark as read
            await self.send_telegram_message(message, context)
            if await self.mark_as_read(article.id):
                logger.info(f"Successfully processed and marked as read: {translated_title}")
            else:
                logger.warning(f"Article processed but failed to mark as read: {translated_title}")

            await asyncio.sleep(1)  # Rate limiting
        except Exception as e:
            logger.error(f"Article processing error: {e}", exc_info=True)

    async def get_auth_token(self) -> bool:
        """Get authentication token from FreshRSS"""
        session = await self.get_session()
        try:
            url = f"{self.config.freshrss_url}/api/greader.php/accounts/ClientLogin"
            params = {
                'Email': self.config.freshrss_user,
                'Passwd': self.config.freshrss_password
            }

            async with session.post(url, params=params) as response:
                if response.status != 200:
                    raise Exception(f"Auth error: {response.status}")

                text = await response.text()
                for line in text.split('\n'):
                    if line.startswith('Auth='):
                        self.auth_token = line.replace('Auth=', '').strip()
                        logger.info("Successfully obtained auth token")
                        return True

                raise Exception("No Auth token in response")
        except Exception as e:
            logger.error(f"Authentication error: {e}")
            return False

    def _convert_greader_to_rss(self, items: List[Dict[str, Any]]) -> List[Article]:
        """Convert Google Reader API items to Article objects"""
        converted = []
        for item in items:
            full_id = item.get('id', '')
            
            article = Article(
                id=full_id,  # Keep the full ID
                guid=full_id.split('/')[-1] if full_id else '',  # Store short ID
                title=item.get('title', ''),
                content=item.get('summary', {}).get('content', ''),
                link=item.get('canonical', [{}])[0].get('href', ''),
                source_title=item.get('origin', {}).get('title', '')
            )
            converted.append(article)
            logger.debug(f"Converted article: {article.title} with ID: {article.id}")
        return converted

    async def fetch_articles(self) -> List[Article]:
        """Fetch unread articles from FreshRSS"""
        if not self.auth_token and not await self.get_auth_token():
            return []

        session = await self.get_session()
        try:
            url = f"{self.config.freshrss_url}/api/greader.php/reader/api/0/stream/contents/user/-/state/com.google/reading-list"
            headers = {"Authorization": f"GoogleLogin auth={self.auth_token}"}
            params = {
                'output': 'json',
                'n': ARTICLES_PER_FETCH,
                'xt': 'user/-/state/com.google/read'
            }

            async with session.get(url, headers=headers, params=params) as response:
                if response.status == 401:
                    if await self.get_auth_token():
                        return await self.fetch_articles()
                    return []

                if response.status != 200:
                    raise Exception(f"FreshRSS API error: {response.status}")

                data = await response.json()
                # Filter items before converting them
                unread_items = [
                    item for item in data.get('items', [])
                    if item.get('id') not in self.marked_as_read
                ]
                articles = self._convert_greader_to_rss(unread_items)
                logger.debug(f"Fetched {len(articles)} unread articles")
                return articles

        except Exception as e:
            logger.error(f"FreshRSS fetch error: {e}")
            return []

async def run_bot(application: Application, translator: RSSTranslator) -> None:
    """Run the bot main loop"""
    try:
        async with application:
            await application.initialize()
            await application.start()
            logger.info("Bot started successfully")

            while True:
                if translator.is_running:
                    try:
                        articles = await translator.fetch_articles()
                        logger.info(f"Found {len(articles)} unread articles")

                        for article in articles:
                            if translator.is_running:
                                await translator.process_article(article, application)
                    except Exception as e:
                        logger.error(f"Error in feed check: {e}")

                await asyncio.sleep(FEED_CHECK_INTERVAL)
    except Exception as e:
        logger.error(f"Error in run_bot: {e}", exc_info=True)
    finally:
        await application.stop()
        await translator.close_session()

async def main() -> None:
    """Main entry point"""
    config = Config.from_env()
    global logger
    logger = setup_logging(config.log_level)
    
    logger.info("Starting RSS Translator Bot")
    translator = RSSTranslator(config)

    try:
        application = Application.builder().token(config.telegram_token).build()
        await run_bot(application, translator)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}", exc_info=True)
        raise
    finally:
        await translator.close_session()

if __name__ == '__main__':
    asyncio.run(main())