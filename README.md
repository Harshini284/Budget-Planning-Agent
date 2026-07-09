# AI Budget Planning Agent

A full-stack Flask application that helps users track income, manage expenses, receive AI-style budget guidance, and export financial reports.

## Features
- User registration and login
- Profile setup with monthly salary and savings target
- Add income and expense transactions
- Dashboard with financial KPIs, AI recommendations, and a budget plan
- Interactive Plotly charts
- Excel and PDF report export
- A lightweight ML model saved as model.pkl for savings forecasting

## Project Structure
- app.py: Main Flask application and database setup
- templates/: HTML pages for landing, auth, dashboard, budget, and reports
- static/: CSS and JavaScript assets
- dataset/budget_dataset.csv: Sample training dataset for the ML model
- model.pkl: Trained regression model generated on first run
- exports/: Generated Excel and PDF downloads

## How to Run
1. Install dependencies:
   ```bash
   py -m pip install -r requirements.txt
   ```
2. Start the app:
   ```bash
   py app.py
   ```
3. Open the app in your browser:
   ```text
   http://127.0.0.1:5000/
   ```

## Notes
The application uses SQLite by default for a ready-to-run local experience. The ML model is trained automatically on first launch if model.pkl is not present.
