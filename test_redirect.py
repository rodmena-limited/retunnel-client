#!/usr/bin/env python3
"""Test script for redirect handling"""

from flask import Flask, redirect
import sys

app = Flask(__name__)

@app.route('/')
def index():
    return '<h1>Home Page</h1><a href="/backend/">Go to backend</a>'

@app.route('/backend/')
def backend_slash():
    # This should trigger a redirect
    return redirect('/backend/dashboard')

@app.route('/backend/dashboard')
def dashboard():
    return '<h1>Backend Dashboard</h1><p>If you see this, redirects are working!</p>'

@app.route('/absolute')
def absolute_redirect():
    # Test absolute localhost redirect
    return redirect('http://localhost:5000/backend/dashboard')

@app.route('/external')
def external_redirect():
    # Test external redirect (should not be rewritten)
    return redirect('https://www.google.com')

if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    print(f"Starting test server on port {port}")
    print("Test URLs:")
    print(f"  http://localhost:{port}/            - Home page")
    print(f"  http://localhost:{port}/backend/    - Should redirect to /backend/dashboard")
    print(f"  http://localhost:{port}/absolute    - Should redirect to absolute localhost URL")
    print(f"  http://localhost:{port}/external    - Should redirect to external URL")
    app.run(port=port, debug=True)