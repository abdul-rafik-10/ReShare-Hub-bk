from flask import Flask, request, jsonify
import google.generativeai as genai
from PIL import Image
import io
import os
import re
from flask_cors import CORS
from dotenv import load_dotenv
from flask_limiter import Limiter

if os.environ.get('FLASK_ENV') != 'production':
    load_dotenv()

app = Flask(__name__)
CORS(app)
genai.configure(api_key=os.getenv("API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

limiter = Limiter(
    app=app,
    key_func=lambda: request.remote_addr,
    default_limits=["200 per day", "50 per hour"]
)

# --------------------- ORIGINAL PROMPTS (NO CHANGES) ---------------------
reusability_prompt = """
You're a smart product evaluator. Based on the image and text description of a second-hand product, determine if this product is reasonably **reusable**.

Please answer clearly with **"Yes" or "No"**, followed by a brief explanation (2–4 sentences) of your reasoning.

Consider:
* Whether the product still functions or can serve its intended purpose.
* If it shows cosmetic damage, whether that damage affects its usability.
* If any parts are missing or broken beyond repair.

Your answer should help a customer understand why the product is or isn't reusable.
"""

category_prompt = """
You are provided with a product description. Categorize the product into one of the following categories and subcategories:

* *Electronics*
  - Subcategories: Mobile Phones, Laptops, Calculators, Tablets, Accessories, Others
* *Furniture*
  - Subcategories: Dining tables, Study tables, Chairs, Sofas, Beds, Others
* *Appliances*
  - Subcategories: Kitchen Appliances, Home Appliances, Air Conditioners, Others
* *Books*
  - Subcategories: Fiction, Non-fiction, Textbooks, Comics, Others
* *Clothing*
  - Subcategories: Men's Wear, Women's Wear, Children's Wear, Accessories, Others
* *Miscellaneous*
  - Subcategory: Miscellaneous

Please categorize the following product description into the most appropriate category and subcategory.

[Product Description Here]

Provide the output in the following format:
Category: [Category Name]
Subcategory: [Subcategory Name]
"""

sales_pitch_prompt = """
You are a helpful product assistant. Based on the product image, generate a product *title* and *detailed description*.

*Title: Keep it clear, simple, and neat—no more than 5 words*. It should quickly capture what the product is. Avoid unnecessary punctuation or buzzwords.

*Description: Write a **friendly, warm, and approachable product description* that is *150 to 200 words long*. Speak as if you're talking to a customer in a store—keep it reassuring, informative, and easy to understand. 

Emphasize that the product is *second-hand but in excellent condition, thoroughly checked, and still a **reliable and valuable choice*. Avoid technical jargon—use everyday language that builds trust.

Reassure the customer that second-hand items often offer *great value for money, combining quality and affordability. Highlight **practical benefits* like ease of use, durability, and how it fits into *daily routines*—whether that's at home, at work, while traveling, or during hobbies.

Make it clear the product isn’t just for occasional use—it’s something they can *rely on again and again. Help them feel **confident and positive* about choosing this item.

The goal is to make the customer feel like buying second-hand is a *smart, practical, and safe* decision.

Return your answer in this format:

Title: [Insert simple 5-word title here]
Description: [Insert 150–200 word description here]
"""
# --------------------- END PROMPTS ---------------------

def clean_response(text):
    return re.sub(r'\*{2,}|_{2,}', '', text).strip()

def parse_sales_response(text):
    """Properly parse title and description from response"""
    try:
        title_part, desc_part = text.split("Description:", 1)
        title = title_part.replace("Title:", "").strip()
        description = desc_part.strip()
        return title, description
    except Exception as e:
        app.logger.error(f"Failed to parse response: {str(e)}")
        return text.split('\n')[0][:50].strip(), text  # Fallback

@app.route('/generate-content', methods=['POST'])
@limiter.limit("5 per minute")
def generate_content():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        img_file = request.files['image']
        if img_file.content_length > 5 * 1024 * 1024:
            return jsonify({'error': 'Image exceeds 5MB size limit'}), 400

        try:
            img_bytes = img_file.read()
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            return jsonify({'error': f'Invalid image: {str(e)}'}), 400

        # Reusability check
        try:
            reuse_response = model.generate_content([reusability_prompt, img])
            reuse_text = clean_response(reuse_response.text)
            is_reusable = bool(re.search(r'\byes\b', reuse_text, re.IGNORECASE))
        except Exception as e:
            return jsonify({'error': f'Reusability check failed: {str(e)}'}), 500

        if not is_reusable:
            return jsonify({
                'reusable': False,
                'reason': reuse_text.split('\n')[0][:200]
            })

        # Description generation
        try:
            desc_response = model.generate_content([sales_pitch_prompt, img])
            raw_description = clean_response(desc_response.text)
            title, description = parse_sales_response(raw_description)
        except Exception as e:
            return jsonify({'error': f'Description failed: {str(e)}'}), 500

        # Category parsing
        category = "Miscellaneous"
        subcategory = "Miscellaneous"
        try:
            cat_response = model.generate_content([
                "STRICT FORMAT:\nCategory: <value>\nSubcategory: <value>\n\n"
                "Analyze image and follow structure exactly.", 
                img
            ])
            
            category_match = re.search(r'Category:\s*([^\n]+)', cat_response.text, re.IGNORECASE)
            subcat_match = re.search(r'Subcategory:\s*([^\n]+)', cat_response.text, re.IGNORECASE)
            
            if category_match:
                category = category_match.group(1).strip().title()
                valid_cats = ["Electronics", "Furniture", "Appliances", "Books", "Clothing", "Miscellaneous"]
                category = category if category in valid_cats else "Miscellaneous"
            
            if subcat_match:
                subcategory = subcat_match.group(1).strip().title()
                if subcategory.lower() in ['others', 'other']:
                    subcategory = "Miscellaneous"
        except Exception as e:
            app.logger.error(f'Category error: {str(e)}')

        return jsonify({
            'reusable': True,
            'title': title,
            'description': description,
            'category': category,
            'subcategory': subcategory,
            'reason': reuse_text[:200]
        })

    except Exception as e:
        app.logger.error(f'Server error: {str(e)}')
        return jsonify({'error': 'Internal error'}), 500

# Rest of the endpoints remain unchanged...
# [Keep the /check-reusability and /health endpoints exactly as before]

@app.route('/check-reusability', methods=['POST'])
@limiter.limit("5 per minute")
def check_reusability():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image'}), 400

        img_file = request.files['image']
        if img_file.content_length > 5 * 1024 * 1024:
            return jsonify({'error': 'Image too large (max 5MB)'}), 400

        try:
            img_bytes = img_file.read()
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            return jsonify({'error': f'Invalid image: {str(e)}'}), 400

        try:
            response = model.generate_content([reusability_prompt, img])
            text = clean_response(response.text)
            is_reusable = bool(re.search(r'\byes\b', text, re.IGNORECASE))
        except Exception as e:
            return jsonify({'error': f'Check failed: {str(e)}'}), 500

        return jsonify({
            'reusable': is_reusable,
            'reason': text.split('\n')[0][:200]
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        'status': 'healthy',
        'version': '1.0',
        'dependencies': ['Flask', 'Google-GenerativeAI']
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
