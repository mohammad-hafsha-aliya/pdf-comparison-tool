# PDF Comparison Tool

import os
import sys
import difflib
from flask import Flask, render_template, request, jsonify, redirect, url_for
import tempfile
import uuid
import fitz  # PyMuPDF
import re
from werkzeug.utils import secure_filename
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = tempfile.mkdtemp()
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload size

class PDFComparer:
    def __init__(self):
        self.comparison_results = {}
    
    def extract_text_from_pdf(self, pdf_path):
        """Extract text from PDF using PyMuPDF for better text extraction"""
        try:
            text_by_page = []
            doc = fitz.open(pdf_path)
            
            for page_num in range(len(doc)):
                page = doc.load_page(page_num)
                text = page.get_text("text")
                # Clean up text - remove extra whitespace, normalize line endings
                text = re.sub(r'\s+', ' ', text)
                text = text.strip()
                text_by_page.append(text)
            
            doc.close()
            return text_by_page
        except Exception as e:
            logger.error(f"Error extracting text from PDF {pdf_path}: {e}")
            raise

    def compare_pdfs(self, pdf1_path, pdf2_path):
        """Compare two PDFs and return differences"""
        try:
            # Extract text from both PDFs
            text1_by_page = self.extract_text_from_pdf(pdf1_path)
            text2_by_page = self.extract_text_from_pdf(pdf2_path)
            
            # Compare the PDFs page by page
            comparison_id = str(uuid.uuid4())
            results = {
                'comparison_id': comparison_id,
                'pdf1_pages': len(text1_by_page),
                'pdf2_pages': len(text2_by_page),
                'page_comparisons': [],
                'metadata_diff': self.compare_metadata(pdf1_path, pdf2_path)
            }
            
            # Compare as many pages as we can
            for i in range(max(len(text1_by_page), len(text2_by_page))):
                page_result = {
                    'page_number': i + 1,
                    'differences': []
                }
                
                # If both PDFs have this page
                if i < len(text1_by_page) and i < len(text2_by_page):
                    # Split text into lines and compare
                    text1_lines = text1_by_page[i].split('\n')
                    text2_lines = text2_by_page[i].split('\n')
                    
                    # Create a diff using difflib
                    d = difflib.Differ()
                    diff = list(d.compare(text1_lines, text2_lines))
                    
                    # Process the differences
                    for line in diff:
                        if line.startswith('- '):
                            page_result['differences'].append({
                                'type': 'removed',
                                'content': line[2:]
                            })
                        elif line.startswith('+ '):
                            page_result['differences'].append({
                                'type': 'added',
                                'content': line[2:]
                            })
                        elif line.startswith('? '):
                            # Skip the markers
                            continue
                        else:
                            # Common line, starts with '  '
                            page_result['differences'].append({
                                'type': 'common',
                                'content': line[2:]
                            })
                else:
                    # This page exists in only one of the PDFs
                    if i < len(text1_by_page):
                        page_result['differences'].append({
                            'type': 'page_only_in_pdf1',
                            'content': text1_by_page[i]
                        })
                    else:
                        page_result['differences'].append({
                            'type': 'page_only_in_pdf2',
                            'content': text2_by_page[i]
                        })
                
                results['page_comparisons'].append(page_result)
            
            # Calculate overall similarity score (simple version)
            total_lines = 0
            common_lines = 0
            
            for page in results['page_comparisons']:
                for diff in page['differences']:
                    if diff['type'] in ['added', 'removed', 'common']:
                        total_lines += 1
                        if diff['type'] == 'common':
                            common_lines += 1
            
            if total_lines > 0:
                results['similarity_score'] = (common_lines / total_lines) * 100
            else:
                results['similarity_score'] = 0
                
            self.comparison_results[comparison_id] = results
            return results
        
        except Exception as e:
            logger.error(f"Error comparing PDFs: {e}")
            return {
                'error': str(e),
                'comparison_id': None
            }

    def compare_metadata(self, pdf1_path, pdf2_path):
        """Compare metadata between two PDFs using PyMuPDF"""
        try:
            # Extract metadata using PyMuPDF
            doc1 = fitz.open(pdf1_path)
            doc2 = fitz.open(pdf2_path)
            
            # Get metadata
            meta1 = doc1.metadata
            meta2 = doc2.metadata
            
            # Close documents
            doc1.close()
            doc2.close()
            
            # Compare metadata
            all_keys = set(meta1.keys()).union(set(meta2.keys()))
            metadata_diff = []
            
            for key in all_keys:
                val1 = meta1.get(key, None)
                val2 = meta2.get(key, None)
                
                if val1 != val2:
                    metadata_diff.append({
                        'key': key,
                        'pdf1_value': val1,
                        'pdf2_value': val2
                    })
            
            return metadata_diff
        except Exception as e:
            logger.error(f"Error comparing PDF metadata: {e}")
            return [{'error': str(e)}]

    def get_comparison_result(self, comparison_id):
        """Retrieve a saved comparison result"""
        return self.comparison_results.get(comparison_id)

# Initialize the PDF comparer
pdf_comparer = PDFComparer()

# Flask routes
@app.route('/')
def index():
    return render_template('index.html')

@app.route('/compare', methods=['POST'])
def compare():
    if 'pdf1' not in request.files or 'pdf2' not in request.files:
        return jsonify({'error': 'Both PDF files are required'}), 400
    
    pdf1 = request.files['pdf1']
    pdf2 = request.files['pdf2']
    
    if pdf1.filename == '' or pdf2.filename == '':
        return jsonify({'error': 'Both PDF files are required'}), 400
    
    try:
        # Save uploaded files
        pdf1_filename = secure_filename(pdf1.filename)
        pdf2_filename = secure_filename(pdf2.filename)
        
        pdf1_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{pdf1_filename}")
        pdf2_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{uuid.uuid4()}_{pdf2_filename}")
        
        pdf1.save(pdf1_path)
        pdf2.save(pdf2_path)
        
        # Compare PDFs
        results = pdf_comparer.compare_pdfs(pdf1_path, pdf2_path)
        
        # Clean up temporary files
        try:
            os.remove(pdf1_path)
            os.remove(pdf2_path)
        except:
            pass
        
        if 'error' in results:
            return jsonify({'error': results['error']}), 500
        
        # Redirect to results page
        return redirect(url_for('view_results', comparison_id=results['comparison_id']))
    
    except Exception as e:
        logger.error(f"Error in compare route: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/results/<comparison_id>')
def view_results(comparison_id):
    results = pdf_comparer.get_comparison_result(comparison_id)
    if not results:
        return "Comparison results not found", 404
    
    return render_template('results.html', results=results)

@app.route('/api/comparison/<comparison_id>')
def get_comparison_api(comparison_id):
    results = pdf_comparer.get_comparison_result(comparison_id)
    if not results:
        return jsonify({'error': 'Comparison results not found'}), 404
    
    return jsonify(results)

# HTML Templates
# Create a templates directory and add these HTML files

def create_templates():
    os.makedirs('templates', exist_ok=True)
    
    # index.html
    with open('templates/index.html', 'w') as f:
        f.write('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF Comparison Tool</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            padding-top: 20px;
        }
        .container {
            max-width: 800px;
        }
        .upload-area {
            border: 2px dashed #ccc;
            padding: 20px;
            text-align: center;
            margin-bottom: 20px;
            border-radius: 5px;
            cursor: pointer;
        }
        .upload-area.highlight {
            border-color: #007bff;
            background-color: #f8f9fa;
        }
        #compareBtn {
            display: none;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1 class="text-center mb-4">PDF Comparison Tool</h1>
        
        <form id="uploadForm" action="/compare" method="post" enctype="multipart/form-data">
            <div class="row">
                <div class="col-md-6">
                    <div class="card mb-4">
                        <div class="card-header">
                            PDF 1
                        </div>
                        <div class="card-body">
                            <div id="uploadArea1" class="upload-area">
                                <p>Drag & drop PDF here or click to browse</p>
                                <input type="file" id="pdf1" name="pdf1" accept=".pdf" style="display: none;">
                            </div>
                            <div id="fileInfo1" class="d-none">
                                <p class="mb-0">Selected file: <span id="fileName1"></span></p>
                                <button type="button" class="btn btn-link p-0" id="clearFile1">Clear</button>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card mb-4">
                        <div class="card-header">
                            PDF 2
                        </div>
                        <div class="card-body">
                            <div id="uploadArea2" class="upload-area">
                                <p>Drag & drop PDF here or click to browse</p>
                                <input type="file" id="pdf2" name="pdf2" accept=".pdf" style="display: none;">
                            </div>
                            <div id="fileInfo2" class="d-none">
                                <p class="mb-0">Selected file: <span id="fileName2"></span></p>
                                <button type="button" class="btn btn-link p-0" id="clearFile2">Clear</button>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="text-center">
                <button type="submit" id="compareBtn" class="btn btn-primary btn-lg">Compare PDFs</button>
            </div>
        </form>
        
        <div id="loadingIndicator" class="text-center d-none">
            <div class="spinner-border text-primary" role="status">
                <span class="visually-hidden">Loading...</span>
            </div>
            <p>Comparing PDFs... This may take a few moments.</p>
        </div>
    </div>

    <script>
        document.addEventListener('DOMContentLoaded', function() {
            const uploadAreas = document.querySelectorAll('.upload-area');
            const fileInputs = [document.getElementById('pdf1'), document.getElementById('pdf2')];
            const fileInfos = [document.getElementById('fileInfo1'), document.getElementById('fileInfo2')];
            const fileNames = [document.getElementById('fileName1'), document.getElementById('fileName2')];
            const clearBtns = [document.getElementById('clearFile1'), document.getElementById('clearFile2')];
            const compareBtn = document.getElementById('compareBtn');
            const loadingIndicator = document.getElementById('loadingIndicator');
            const uploadForm = document.getElementById('uploadForm');
            
            // Setup drag and drop for upload areas
            uploadAreas.forEach((area, index) => {
                area.addEventListener('click', () => fileInputs[index].click());
                
                area.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    area.classList.add('highlight');
                });
                
                area.addEventListener('dragleave', () => {
                    area.classList.remove('highlight');
                });
                
                area.addEventListener('drop', (e) => {
                    e.preventDefault();
                    area.classList.remove('highlight');
                    
                    if (e.dataTransfer.files.length) {
                        const file = e.dataTransfer.files[0];
                        if (file.type === 'application/pdf') {
                            fileInputs[index].files = e.dataTransfer.files;
                            updateFileInfo(index, file.name);
                        } else {
                            alert('Please upload a PDF file.');
                        }
                    }
                });
            });
            
            // Handle file selection
            fileInputs.forEach((input, index) => {
                input.addEventListener('change', () => {
                    if (input.files.length) {
                        updateFileInfo(index, input.files[0].name);
                    }
                });
            });
            
            // Handle clear buttons
            clearBtns.forEach((btn, index) => {
                btn.addEventListener('click', (e) => {
                    e.preventDefault();
                    fileInputs[index].value = '';
                    uploadAreas[index].classList.remove('d-none');
                    fileInfos[index].classList.add('d-none');
                    checkBothFilesSelected();
                });
            });
            
            // Handle form submission
            uploadForm.addEventListener('submit', (e) => {
                if (!fileInputs[0].files.length || !fileInputs[1].files.length) {
                    e.preventDefault();
                    alert('Please select two PDF files to compare.');
                    return;
                }
                
                compareBtn.classList.add('d-none');
                loadingIndicator.classList.remove('d-none');
            });
            
            // Update file info display
            function updateFileInfo(index, name) {
                fileNames[index].textContent = name;
                uploadAreas[index].classList.add('d-none');
                fileInfos[index].classList.remove('d-none');
                checkBothFilesSelected();
            }
            
            // Check if both files are selected
            function checkBothFilesSelected() {
                if (fileInputs[0].files.length && fileInputs[1].files.length) {
                    compareBtn.style.display = 'inline-block';
                } else {
                    compareBtn.style.display = 'none';
                }
            }
        });
    </script>
</body>
</html>
        ''')
    
    # results.html
    with open('templates/results.html', 'w') as f:
        f.write('''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PDF Comparison Results</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/css/bootstrap.min.css" rel="stylesheet">
    <style>
        body {
            padding: 20px 0;
        }
        .diff-added {
            background-color: #e6ffed;
            border-left: 4px solid #2cbe4e;
            padding-left: 10px;
        }
        .diff-removed {
            background-color: #ffeef0;
            border-left: 4px solid #cb2431;
            padding-left: 10px;
        }
        .diff-common {
            padding-left: 14px;
        }
        .nav-pills .nav-link.active {
            background-color: #6c757d;
        }
        .page-only-notice {
            background-color: #f8f9fa;
            padding: 10px;
            border-radius: 5px;
            margin-bottom: 10px;
            border-left: 4px solid #0dcaf0;
        }
        .similarity-high {
            color: #2cbe4e;
        }
        .similarity-medium {
            color: #f0ad4e;
        }
        .similarity-low {
            color: #cb2431;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1>PDF Comparison Results</h1>
            <a href="/" class="btn btn-outline-primary">New Comparison</a>
        </div>
        
        <div class="card mb-4">
            <div class="card-header">
                Summary
            </div>
            <div class="card-body">
                <div class="row">
                    <div class="col-md-4">
                        <div class="mb-3">
                            <h5>Similarity Score</h5>
                            <h2 class="
                                {% if results.similarity_score >= 80 %}similarity-high
                                {% elif results.similarity_score >= 50 %}similarity-medium
                                {% else %}similarity-low{% endif %}
                            ">{{ "%.1f"|format(results.similarity_score) }}%</h2>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="mb-3">
                            <h5>Page Count</h5>
                            <p>PDF 1: {{ results.pdf1_pages }} pages<br>
                               PDF 2: {{ results.pdf2_pages }} pages</p>
                        </div>
                    </div>
                    <div class="col-md-4">
                        <div class="mb-3">
                            <h5>Metadata Differences</h5>
                            <p>{{ results.metadata_diff|length }} differences found</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        
        <!-- Metadata Differences -->
        {% if results.metadata_diff %}
        <div class="card mb-4">
            <div class="card-header">
                Metadata Differences
            </div>
            <div class="card-body">
                <table class="table table-striped table-bordered">
                    <thead>
                        <tr>
                            <th>Property</th>
                            <th>PDF 1 Value</th>
                            <th>PDF 2 Value</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for diff in results.metadata_diff %}
                        <tr>
                            <td>{{ diff.key }}</td>
                            <td>{{ diff.pdf1_value if diff.pdf1_value is not none else "(not set)" }}</td>
                            <td>{{ diff.pdf2_value if diff.pdf2_value is not none else "(not set)" }}</td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            </div>
        </div>
        {% endif %}
        
        <!-- Page Comparisons -->
        <div class="card">
            <div class="card-header">
                Page-by-Page Comparison
            </div>
            <div class="card-body">
                <ul class="nav nav-pills mb-3" id="pagesTabs" role="tablist">
                    {% for page in results.page_comparisons %}
                    <li class="nav-item" role="presentation">
                        <button class="nav-link {% if loop.index == 1 %}active{% endif %}" 
                                id="page-{{ page.page_number }}-tab" 
                                data-bs-toggle="pill" 
                                data-bs-target="#page-{{ page.page_number }}" 
                                type="button" 
                                role="tab">
                            Page {{ page.page_number }}
                        </button>
                    </li>
                    {% endfor %}
                </ul>
                
                <div class="tab-content" id="pagesTabsContent">
                    {% for page in results.page_comparisons %}
                    <div class="tab-pane fade {% if loop.index == 1 %}show active{% endif %}" 
                         id="page-{{ page.page_number }}" 
                         role="tabpanel">
                        
                        {% if page.differences|selectattr('type', 'eq', 'page_only_in_pdf1')|list %}
                            <div class="page-only-notice">
                                <strong>Note:</strong> This page exists only in PDF 1.
                            </div>
                        {% elif page.differences|selectattr('type', 'eq', 'page_only_in_pdf2')|list %}
                            <div class="page-only-notice">
                                <strong>Note:</strong> This page exists only in PDF 2.
                            </div>
                        {% endif %}
                        
                        <div class="card">
                            <div class="card-header">
                                <div class="form-check form-switch">
                                    <input class="form-check-input show-common-toggle" 
                                           type="checkbox" 
                                           id="showCommon{{ page.page_number }}" 
                                           checked>
                                    <label class="form-check-label" for="showCommon{{ page.page_number }}">
                                        Show unchanged content
                                    </label>
                                </div>
                            </div>
                            <div class="card-body">
                                <div class="diff-container">
                                    {% for diff in page.differences %}
                                        {% if diff.type == 'common' %}
                                            <div class="diff-line diff-common">{{ diff.content }}</div>
                                        {% elif diff.type == 'added' %}
                                            <div class="diff-line diff-added">+ {{ diff.content }}</div>
                                        {% elif diff.type == 'removed' %}
                                            <div class="diff-line diff-removed">- {{ diff.content }}</div>
                                        {% elif diff.type in ['page_only_in_pdf1', 'page_only_in_pdf2'] %}
                                            <div class="diff-line">{{ diff.content }}</div>
                                        {% endif %}
                                    {% endfor %}
                                </div>
                            </div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
    </div>
    
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0-alpha1/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        document.addEventListener('DOMContentLoaded', function() {
            // Handle "Show unchanged content" toggles
            const toggles = document.querySelectorAll('.show-common-toggle');
            
            toggles.forEach(toggle => {
                toggle.addEventListener('change', function() {
                    const tabPane = this.closest('.tab-pane');
                    const commonLines = tabPane.querySelectorAll('.diff-common');
                    
                    if (this.checked) {
                        commonLines.forEach(line => line.style.display = 'block');
                    } else {
                        commonLines.forEach(line => line.style.display = 'none');
                    }
                });
            });
        });
    </script>
</body>
</html>
        ''')

# Main entry point
if __name__ == '__main__':
    # Create templates directory and files
    create_templates()
    
    # Start the Flask app
    app.run(debug=True, host='0.0.0.0', port=500)