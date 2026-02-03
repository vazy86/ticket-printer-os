#!/usr/bin/env python3
"""
Ticket Printing Application for Netum 58mm Thermal Printer
"""
from flask import Flask, request, render_template, jsonify
from datetime import datetime
import logging
from escpos.printer import Usb, Serial, Network, Win32Raw
from PIL import Image, ImageDraw, ImageFont
import os
import textwrap

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Configuration
PRINTER_TYPE = os.getenv('PRINTER_TYPE', 'usb')  # 'usb', 'serial', 'network', 'bluetooth', or 'windows'
USB_VENDOR = int(os.getenv('USB_VENDOR', '0x0416'), 16) if os.getenv('USB_VENDOR') else None
USB_PRODUCT = int(os.getenv('USB_PRODUCT', '0x5011'), 16) if os.getenv('USB_PRODUCT') else None
SERIAL_PORT = os.getenv('SERIAL_PORT', '/dev/ttyUSB0')  # Default serial port
NETWORK_HOST = os.getenv('NETWORK_HOST', '192.168.1.100')
WINDOWS_PRINTER_NAME = os.getenv('WINDOWS_PRINTER_NAME', '')  # Windows printer name (e.g., 'NPI NP-F309')

def get_printer():
    """Initialize and return the printer based on configuration"""
    try:
        if PRINTER_TYPE == 'usb':
            if USB_VENDOR and USB_PRODUCT:
                return Usb(USB_VENDOR, USB_PRODUCT)
            else:
                return Usb(0x0416, 0x5011)
        elif PRINTER_TYPE == 'serial' or PRINTER_TYPE == 'bluetooth':
            # For Bluetooth, use the serial backend via rfcomm
            port = SERIAL_PORT
            if PRINTER_TYPE == 'bluetooth':
                port = '/dev/rfcomm0'  # Default Bluetooth serial port
            return Serial(devfile=port, baudrate=9600)
        elif PRINTER_TYPE == 'network':
            return Network(NETWORK_HOST)
        elif PRINTER_TYPE == 'windows':
            if not WINDOWS_PRINTER_NAME:
                raise ValueError("WINDOWS_PRINTER_NAME environment variable is required for Windows printer")
            return Win32Raw(WINDOWS_PRINTER_NAME)
        else:
            raise ValueError(f"Unknown printer type: {PRINTER_TYPE}")
    except Exception as e:
        logger.error(f"Failed to initialize printer: {e}")
        logger.error(f"Try running: sudo rfcomm bind /dev/rfcomm0 [PRINTER_MAC_ADDRESS]")
        return None

def create_ticket_image(from_name, question, width=384):
    """Create ticket image with Cyrillic support"""
    # Try to use a font that supports Cyrillic
    font_size = 20
    font_size_large = 28
    font_size_small = 18

    # Try different fonts that support Cyrillic
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",      # Windows
        "C:/Windows/Fonts/cour.ttf",       # Windows Courier
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",  # Linux
        "/usr/share/fonts/TTF/DejaVuSans.ttf",  # Linux alternative
        "/System/Library/Fonts/Helvetica.ttc",  # macOS
    ]

    font = None
    font_bold = None
    font_large = None

    for font_path in font_paths:
        try:
            font = ImageFont.truetype(font_path, font_size)
            font_bold = ImageFont.truetype(font_path, font_size)
            font_large = ImageFont.truetype(font_path, font_size_large)
            break
        except (OSError, IOError):
            continue

    if font is None:
        font = ImageFont.load_default()
        font_bold = font
        font_large = font

    # Calculate image height based on content
    now = datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")

    # Wrap long text
    wrapper = textwrap.TextWrapper(width=30)
    question_lines = wrapper.wrap(question)
    from_name_lines = wrapper.wrap(f"От: {from_name}")

    # Calculate height
    line_height = font_size + 5
    line_height_large = font_size_large + 8
    padding = 10

    height = padding  # top padding
    height += line_height_large  # "TICKET"
    height += line_height  # separator
    height += len(from_name_lines) * line_height  # from name
    height += line_height * 2  # time + date
    height += line_height  # separator
    height += line_height  # "Сообщение:"
    height += len(question_lines) * line_height  # question
    height += line_height  # separator
    height += padding * 3  # bottom padding

    # Create image
    img = Image.new('1', (width, height), color=1)  # 1-bit, white background
    draw = ImageDraw.Draw(img)

    y = padding

    # Title
    draw.text((width // 2, y), "TICKET", font=font_large, fill=0, anchor="mt")
    y += line_height_large

    # Separator
    draw.text((width // 2, y), "=" * 32, font=font, fill=0, anchor="mt")
    y += line_height

    # From
    for line in from_name_lines:
        draw.text((padding, y), line, font=font_bold, fill=0)
        y += line_height

    # Time and date
    draw.text((padding, y), f"Время: {time_str}", font=font, fill=0)
    y += line_height
    draw.text((padding, y), f"Дата: {date_str}", font=font, fill=0)
    y += line_height

    # Separator
    draw.text((width // 2, y), "-" * 32, font=font, fill=0, anchor="mt")
    y += line_height

    # Question header
    draw.text((padding, y), "Сообщение:", font=font_bold, fill=0)
    y += line_height

    # Question text
    for line in question_lines:
        draw.text((padding, y), line, font=font, fill=0)
        y += line_height

    # Bottom separator
    draw.text((width // 2, y), "=" * 32, font=font, fill=0, anchor="mt")

    return img


def format_ticket(printer, from_name, question):
    """Format and print the ticket as image for Cyrillic support"""
    try:
        # Create ticket as image
        img = create_ticket_image(from_name, question)

        # Print image
        printer.image(img)
        printer.text("\n\n")
        printer.cut()

        return True
    except Exception as e:
        logger.error(f"Error printing ticket: {e}")
        return False

@app.route('/')
def index():
    """Serve the main page"""
    return render_template('index.html')

@app.route('/submit_ticket', methods=['POST'])
def submit_ticket():
    """Handle ticket submission"""
    try:
        data = request.json
        from_name = data.get('from_name', 'Anonymous')
        question = data.get('question', '')

        if not question.strip():
            return jsonify({'success': False, 'error': 'Question/Comment cannot be empty'}), 400

        printer = get_printer()

        if printer is None:
            return jsonify({'success': False, 'error': 'Printer not available'}), 500

        try:
            # Open printer job (required for Windows printer)
            if PRINTER_TYPE == 'windows':
                printer.open()

            success = format_ticket(printer, from_name, question)

            # Close printer job
            if PRINTER_TYPE == 'windows':
                printer.close()
        except Exception as e:
            logger.error(f"Printer operation failed: {e}")
            success = False

        if success:
            logger.info(f"Ticket printed successfully from: {from_name}")
            return jsonify({'success': True, 'message': 'Ticket printed successfully'})
        else:
            return jsonify({'success': False, 'error': 'Failed to print ticket'}), 500

    except Exception as e:
        logger.error(f"Error processing ticket submission: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    try:
        printer = get_printer()
        printer_status = printer is not None
        return jsonify({
            'status': 'healthy',
            'printer_connected': printer_status
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500

if __name__ == '__main__':
    # Set debug mode based on environment
    DEBUG = os.getenv('DEBUG', 'True').lower() == 'true'
    app.run(host='0.0.0.0', port=5000, debug=DEBUG)