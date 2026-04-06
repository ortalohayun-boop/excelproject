import os
import re
import io
import pandas as pd
from flask import Flask, request, send_file, jsonify
from flask_cors import CORS
from pdf2image import convert_from_bytes
import pytesseract

app = Flask(__name__)
CORS(app)

@app.route('/')
def index():
    return send_file(os.path.join(os.path.dirname(__file__), 'index.html'))

def translate_building_part(text):
    replacements = {
        'Tiny': 'קומה', 'nmi': 'עמוד', 'nmp': 'עמוד',
        'ANIP': 'קומה', 'ANN': 'מרום', 'AMP': 'קומה',
        'poy': 'צפון', 'pom': 'דרום', 'omy': 'מערב', 'poz': 'מזרח',
        'floor': 'קומה', 'column': 'עמוד', 'wall': 'קיר',
        'beam': 'קורה', 'slab': 'רצפה', 'roof': 'גג',
        'N1z;N': 'צפון', 'NAM': 'מרום', 'ONT': '', 'Ns': '',
        'naan': '', 'pon': '', 'p¥ln': '', 'NSS:': '',
    }
    for eng, heb in replacements.items():
        text = text.replace(eng, heb)
    text = re.sub(r'[><%\*\|\.\,\"\'\?]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def extract_data_from_pdf_bytes(pdf_bytes, filename):
    data = {
        "קובץ": filename,
        "מס' תעודה": "",
        "סוג בטון": "",
        "שיעור חוזק ממוצע": "",
        "תאריך יציקה": "",
        "חלק המבנה הנוצק": ""
    }

    try:
        pages = convert_from_bytes(pdf_bytes, dpi=200)
        text = pytesseract.image_to_string(pages[0])
        lines = text.split('\n')

        dates_found = []
        strength_values = []
        first_data_line = None

        for i, line in enumerate(lines):
            if not data["מס' תעודה"]:
                m = re.search(r'\b(20\d{6})\b', line)
                if m:
                    data["מס' תעודה"] = m.group(1)

            m = re.search(r'(\d{2}/\d{2}/20\d{2})', line)
            if m:
                dates_found.append((i, m.group(1)))

            if not data["סוג בטון"]:
                m = re.search(r'\b(\d{2,3})\s*-\s*[2בB]', line)
                if m and 20 <= int(m.group(1)) <= 120:
                    data["סוג בטון"] = "B-" + m.group(1)

            m = re.match(r'^(\d{2,3}\.\d)\s+\d{2,3}\.\d', line)
            if m:
                strength_values.append(float(m.group(1)))
                if first_data_line is None:
                    first_data_line = i

        # חלק המבנה - מחפש בטווח רחב לפני הדגימות
        if first_data_line is not None:
            for offset in range(3, 15):
                idx = first_data_line - offset
                if idx >= 0:
                    candidate = lines[idx].strip()
                    # שורה עם מספר ומילות מבנה
                    if (candidate and re.search(r'\d+', candidate) and
                        len(candidate) > 4 and
                        re.search(r'nmi|nmp|Tiny|ANIP|AMP|ANN|NAM|floor|column|oy|ANT', candidate, re.IGNORECASE)):
                        data["חלק המבנה הנוצק"] = translate_building_part(candidate)
                        break

        if len(dates_found) >= 2:
            data["תאריך יציקה"] = dates_found[1][1]
        elif len(dates_found) == 1:
            data["תאריך יציקה"] = dates_found[0][1]

        if len(strength_values) >= 5:
            data["שיעור חוזק ממוצע"] = strength_values[4]
        elif len(strength_values) >= 4:
            data["שיעור חוזק ממוצע"] = strength_values[3]
        elif strength_values:
            data["שיעור חוזק ממוצע"] = strength_values[-1]

    except Exception as e:
        data["שגיאה"] = str(e)

    return data


@app.route('/process-one', methods=['POST'])
def process_one():
    if 'file' not in request.files:
        return jsonify({"error": "לא הועלה קובץ"}), 400
    file = request.files['file']
    if not file.filename.endswith('.pdf'):
        return jsonify({"error": "קובץ לא תקין"}), 400
    pdf_bytes = file.read()
    result = extract_data_from_pdf_bytes(pdf_bytes, file.filename)
    return jsonify(result)


@app.route('/export', methods=['POST'])
def export_excel():
    data_list = request.json
    if not data_list:
        return jsonify({"error": "אין נתונים"}), 400
    df = pd.DataFrame(data_list)
    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name='results_concrete_tests.xlsx'
    )


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
