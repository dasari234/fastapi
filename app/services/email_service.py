# import logging
# from email.mime.multipart import MIMEMultipart
# from email.mime.text import MIMEText
# from typing import Optional

# import aiosmtplib

# from app.config import FROM_EMAIL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

# logger = logging.getLogger(__name__)

# class EmailService:
    
#     async def send_email(
#         self, 
#         to_email: str, 
#         subject: str, 
#         html_content: str,
#         text_content: Optional[str] = None
#     ) -> bool:
#         """Send email using SMTP"""
#         try:
#             # Create message
#             message = MIMEMultipart("alternative")
#             message["Subject"] = subject
#             message["From"] = FROM_EMAIL
#             message["To"] = to_email
            
#             # Create plain text version if not provided
#             if not text_content:
#                 # Simple HTML to text conversion
#                 import re
#                 text_content = re.sub('<[^<]+?>', '', html_content)
            
#             # Add parts to message
#             part1 = MIMEText(text_content, "plain")
#             part2 = MIMEText(html_content, "html")
#             message.attach(part1)
#             message.attach(part2)
            
#             # Send email
#             async with aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT) as server:
#                 await server.login(SMTP_USER, SMTP_PASSWORD)
#                 await server.sendmail(FROM_EMAIL, to_email, message.as_string())
            
#             logger.info(f"Email sent to {to_email}")
#             return True
            
#         except Exception as e:
#             logger.error(f"Failed to send email to {to_email}: {e}")
#             return False

# # Create global instance
# email_service = EmailService()


import logging
import re
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Optional

import aiosmtplib

from app.config import FROM_EMAIL, SMTP_HOST, SMTP_PASSWORD, SMTP_PORT, SMTP_USER

logger = logging.getLogger(__name__)

class EmailService:
    
    async def send_email(
        self, 
        to_email: str, 
        subject: str, 
        html_content: str,
        text_content: Optional[str] = None
    ) -> bool:
        """Send email using SMTP (supports Gmail and local relay)"""
        try:
            # Build message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = FROM_EMAIL
            message["To"] = to_email

            if not text_content:
                text_content = re.sub('<[^<]+?>', '', html_content)

            message.attach(MIMEText(text_content, "plain"))
            message.attach(MIMEText(html_content, "html"))

            # Create SMTP client
            server = aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT, start_tls=False)

            await server.connect()

            # Gmail / authenticated SMTP
            if SMTP_USER and SMTP_PASSWORD:
                # If using Gmail on port 587 → upgrade to TLS first
                if SMTP_PORT == 587:
                    await server.starttls(tls_context=ssl.create_default_context())
                await server.login(SMTP_USER, SMTP_PASSWORD)
                logger.debug("Authenticated SMTP connection established")

            else:
                logger.debug("Using local SMTP relay without authentication")

            # Send email
            await server.sendmail(FROM_EMAIL, [to_email], message.as_string())
            await server.quit()

            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}", exc_info=True)
            return False


# Global instance
email_service = EmailService()
 