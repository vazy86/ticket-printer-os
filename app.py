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
import sys

# Windows-specific imports for GDI printing
if sys.platform == 'win32':
    try:
        import win32print
        import win32ui
        from PIL import ImageWin
        WINDOWS_GDI_AVAILABLE = True
    except ImportError:
        WINDOWS_GDI_AVAILABLE = False
else:
    WINDOWS_GDI_AVAILABLE = False

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
    font_size = 20
    font_size_large = 28

    # Try different fonts that support Cyrillic
    font_paths = [
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
    ]

    font = None
    font_large = None

    for font_path in font_paths:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, font_size)
                font_large = ImageFont.truetype(font_path, font_size_large)
                logger.info(f"Using font: {font_path}")
                break
            except (OSError, IOError):
                continue

    if font is None:
        logger.warning("No TrueType font found, using default")
        font = ImageFont.load_default()
        font_large = font

    now = datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")

    # Wrap long text
    wrapper = textwrap.TextWrapper(width=28)
    question_lines = wrapper.wrap(question) if question else [""]
    from_name_lines = wrapper.wrap(f"От: {from_name}") if from_name else ["От: Аноним"]

    # Calculate height
    line_height = 26
    line_height_large = 36
    padding = 15

    height = padding
    height += line_height_large
    height += line_height
    height += len(from_name_lines) * line_height
    height += line_height * 2
    height += line_height
    height += line_height
    height += len(question_lines) * line_height
    height += line_height
    height += padding * 2

    # Create RGB image (white background, black text)
    img = Image.new('RGB', (width, height), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)

    y = padding

    # Title
    draw.text((width // 2, y), "TICKET", font=font_large, fill=(0, 0, 0), anchor="mt")
    y += line_height_large

    # Separator line
    draw.line([(10, y), (width - 10, y)], fill=(0, 0, 0), width=2)
    y += line_height

    # From
    for line in from_name_lines:
        draw.text((padding, y), line, font=font, fill=(0, 0, 0))
        y += line_height

    # Time and date
    draw.text((padding, y), f"Время: {time_str}", font=font, fill=(0, 0, 0))
    y += line_height
    draw.text((padding, y), f"Дата: {date_str}", font=font, fill=(0, 0, 0))
    y += line_height

    # Separator
    draw.line([(10, y), (width - 10, y)], fill=(0, 0, 0), width=1)
    y += line_height

    # Message header
    draw.text((padding, y), "Сообщение:", font=font, fill=(0, 0, 0))
    y += line_height

    # Message text
    for line in question_lines:
        draw.text((padding, y), line, font=font, fill=(0, 0, 0))
        y += line_height

    # Bottom separator
    draw.line([(10, y), (width - 10, y)], fill=(0, 0, 0), width=2)

    # Convert: RGB -> Grayscale -> 1-bit (with dithering for better quality)
    img = img.convert('L')
    img = img.point(lambda x: 0 if x < 128 else 255, '1')

    return img


def print_ticket_windows_gdi(printer_name, from_name, question):
    """Print ticket using Windows GDI API with full Cyrillic support"""
    if not WINDOWS_GDI_AVAILABLE:
        raise Exception("Windows GDI printing not available")

    now = datetime.now()
    time_str = now.strftime("%H:%M")
    date_str = now.strftime("%d.%m.%Y")

    # Create the ticket text
    ticket_text = f"""
================================
           TICKET
================================

От: {from_name}
Время: {time_str}
Дата: {date_str}

--------------------------------
Сообщение:

{question}

================================


"""

    # Get printer handle
    hprinter = win32print.OpenPrinter(printer_name)
    try:
        # Start a print job
        job_info = win32print.StartDocPrinter(hprinter, 1, ("Ticket", None, "RAW"))
        try:
            win32print.StartPagePrinter(hprinter)
            # Send text encoded as UTF-8 or CP1251
            win32print.WritePrinter(hprinter, ticket_text.encode('cp1251', errors='replace'))
            win32print.EndPagePrinter(hprinter)
        finally:
            win32print.EndDocPrinter(hprinter)
    finally:
        win32print.ClosePrinter(hprinter)

    return True


def format_ticket(printer, from_name, question):
    """Format and print the ticket using ESC/POS (for non-Windows printers)"""
    try:
        now = datetime.now()
        time_str = now.strftime("%H:%M")
        date_str = now.strftime("%d.%m.%Y")

        # Print ticket
        printer.set(align='center', font='a', width=2, height=2, bold=True)
        printer.text("TICKET\n")

        printer.set(align='center', font='a', width=1, height=1, bold=False)
        printer.text("================================\n")

        printer.set(align='left', font='a', width=1, height=1, bold=True)
        printer.text(f"From: {from_name}\n")

        printer.set(align='left', font='a', width=1, height=1, bold=False)
        printer.text(f"Time: {time_str}\n")
        printer.text(f"Date: {date_str}\n")

        printer.text("--------------------------------\n")

        printer.set(align='left', font='a', width=1, height=1, bold=True)
        printer.text("Message:\n")

        printer.set(align='left', font='a', width=1, height=1, bold=False)
        printer.text(f"{question}\n")

        printer.text("================================\n")
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

        # Use Windows GDI printing for Windows printers (supports Cyrillic)
        if PRINTER_TYPE == 'windows' and WINDOWS_GDI_AVAILABLE:
            try:
                success = print_ticket_windows_gdi(WINDOWS_PRINTER_NAME, from_name, question)
            except Exception as e:
                logger.error(f"Windows GDI printing failed: {e}")
                success = False
        else:
            # Use ESC/POS for other printer types
            printer = get_printer()

            if printer is None:
                return jsonify({'success': False, 'error': 'Printer not available'}), 500

            try:
                if PRINTER_TYPE == 'windows':
                    printer.open()

                success = format_ticket(printer, from_name, question)

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