from flask import Flask, request, jsonify
import google.generativeai as genai
from PIL import Image
import io
import os
import re
from flask_cors import CORS
from dotenv import load_dotenv
load_dotenv()  # Loads .env file
app = Flask(__name__)
CORS(app)
print("API_KEY:", os.getenv("API_KEY"))
genai.configure(api_key=os.getenv("API_KEY"))
model = genai.GenerativeModel("gemini-1.5-flash")

# Original prompts kept exactly as provided
# (Keep all three prompts exactly as in your original code here)
# Prompt templates
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

def clean_response(text):
    """Remove markdown formatting from responses"""
    return re.sub(r'\*{2,}|_{2,}', '', text).strip()

@app.route('/generate-content', methods=['POST'])
def generate_content():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        # Image processing with error handling
        try:
            img_file = request.files['image']
            img_bytes = img_file.read()
            img = Image.open(io.BytesIO(img_bytes))
        except Exception as e:
            return jsonify({'error': f'Invalid image file: {str(e)}'}), 400

        # 1. Enhanced reusability check
        try:
            reuse_response = model.generate_content([reusability_prompt, img])
            reuse_text = clean_response(reuse_response.text)
            is_reusable = bool(re.search(r'\byes\b', reuse_text, re.IGNORECASE))
        except Exception as e:
            return jsonify({'error': f'Reusability check failed: {str(e)}'}), 500

        if not is_reusable:
            return jsonify({
                'reusable': False,
                'reason': reuse_text.split('\n')[0][:200]  # Get first line truncated
            })

        # 2. Generate description
        try:
            desc_response = model.generate_content([sales_pitch_prompt, img])
            description = clean_response(desc_response.text)
        except Exception as e:
            return jsonify({'error': f'Description generation failed: {str(e)}'}), 500

        # 3. Robust category extraction
        category = "Miscellaneous"
        subcategory = "Miscellaneous"
        try:
            cat_response = model.generate_content([
                "STRICT FORMAT:\nCategory: <value>\nSubcategory: <value>\n\n"
                "Analyze image and follow this structure exactly. "
                "Categories: Electronics, Furniture, Appliances, Books, Clothing, Miscellaneous. "
                "Choose closest match.", 
                img
            ])
            
            # Regex-based parsing
            category_match = re.search(r'Category:\s*(.+)', cat_response.text, re.IGNORECASE)
            subcat_match = re.search(r'Subcategory:\s*(.+)', cat_response.text, re.IGNORECASE)
            
            if category_match:
                category = category_match.group(1).strip()
                valid_categories = ["Electronics", "Furniture", "Appliances", "Books", "Clothing", "Miscellaneous"]
                category = category if category in valid_categories else "Miscellaneous"
            
            if subcat_match:
                subcategory = subcat_match.group(1).strip()
                if subcategory.lower() == 'others': 
                    subcategory = "Miscellaneous"
        except Exception as e:
            app.logger.error(f'Category extraction failed: {str(e)}')

        # Generate title from first sentence of description
        title = description.split('.')[0][:50].strip()
        if not title.endswith('.'):
            title += '...'

        return jsonify({
            'reusable': True,
            'title': title,
            'description': description,
            'category': category,
            'subcategory': subcategory,
            'reason': reuse_text[:200]  # Include reusability reason
        })

    except Exception as e:
        app.logger.error(f'Server error: {str(e)}')
        return jsonify({'error': 'Internal server error'}), 500

@app.route('/check-reusability', methods=['POST'])
def check_reusability():
    try:
        if 'image' not in request.files:
            return jsonify({'error': 'No image provided'}), 400

        # Process the image
        img_file = request.files['image']
        img_bytes = img_file.read()
        img = Image.open(io.BytesIO(img_bytes))

        # Use the proper reusability prompt
        try:
            reuse_response = model.generate_content([reusability_prompt, img])  # Changed here
            reuse_text = clean_response(reuse_response.text)
            is_reusable = bool(re.search(r'\byes\b', reuse_text, re.IGNORECASE))
        except Exception as e:
            return jsonify({'error': f'Reusability check failed: {str(e)}'}), 500

        return jsonify({
            'reusable': is_reusable,
            'reason': reuse_text.split('\n')[0][:200]  # Short explanation
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)