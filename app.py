import os
import sqlite3
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from flask import Flask, g, redirect, render_template, request, send_file, session, url_for, flash
from markupsafe import Markup
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "budget_agent.db"
EXPORTS_DIR = BASE_DIR / "exports"
EXPORTS_DIR.mkdir(exist_ok=True)
DATASET_PATH = BASE_DIR / "dataset" / "budget_dataset.csv"
DATASET_PATH.parent.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")


class User:
    def __init__(self, user_id, username, email):
        self.id = user_id
        self.username = username
        self.email = email
        self.is_authenticated = True
        self.is_active = True
        self.is_anonymous = False

    def get_id(self):
        return str(self.id)


class AnonymousUser:
    def __init__(self):
        self.id = None
        self.username = ""
        self.email = ""
        self.is_authenticated = False
        self.is_active = False
        self.is_anonymous = True

    def get_id(self):
        return None


class SimpleField:
    def __init__(self, name, value="", field_type="text", choices=None):
        self.name = name
        self.value = value
        self.field_type = field_type
        self.choices = choices or []
        self.data = value

    def __call__(self, **kwargs):
        attrs = []
        for key, val in kwargs.items():
            attrs.append(f'{key.replace("_", "-")}="{escape(str(val))}"')
        if self.field_type == "select":
            options = []
            for choice_value, choice_label in self.choices:
                selected = " selected" if str(choice_value) == str(self.value) else ""
                options.append(f'<option value="{escape(str(choice_value))}"{selected}>{escape(str(choice_label))}</option>')
            return Markup(f'<select name="{self.name}" ' + " ".join(attrs) + f'>{"".join(options)}</select>')
        if self.field_type == "textarea":
            return Markup(f'<textarea name="{self.name}" ' + " ".join(attrs) + f'>{escape(str(self.value))}</textarea>')
        return Markup(f'<input type="{self.field_type}" name="{self.name}" value="{escape(str(self.value))}" ' + " ".join(attrs) + ">")

    def __str__(self):
        return str(self.value)


class SimpleForm:
    def __init__(self, data=None):
        self.data = data or {}

    def hidden_tag(self):
        return Markup("")

    def validate(self):
        return True


class RegistrationForm(SimpleForm):
    def __init__(self, data=None):
        super().__init__(data)
        self.username = SimpleField("username", self.data.get("username", ""))
        self.email = SimpleField("email", self.data.get("email", ""))
        self.password = SimpleField("password", self.data.get("password", ""), field_type="password")


class LoginForm(SimpleForm):
    def __init__(self, data=None):
        super().__init__(data)
        self.email = SimpleField("email", self.data.get("email", ""))
        self.password = SimpleField("password", self.data.get("password", ""), field_type="password")


class ProfileForm(SimpleForm):
    def __init__(self, data=None):
        super().__init__(data)
        self.phone = SimpleField("phone", self.data.get("phone", ""))
        self.occupation = SimpleField("occupation", self.data.get("occupation", ""))
        self.monthly_salary = SimpleField("monthly_salary", self.data.get("monthly_salary", ""), field_type="number")
        self.savings_goal = SimpleField("savings_goal", self.data.get("savings_goal", ""), field_type="number")


class IncomeForm(SimpleForm):
    def __init__(self, data=None):
        super().__init__(data)
        self.income_type = SimpleField("income_type", self.data.get("income_type", "Salary"), field_type="select", choices=[("Salary", "Salary"), ("Bonus", "Bonus"), ("Business Income", "Business Income"), ("Freelance Income", "Freelance Income"), ("Rental Income", "Rental Income"), ("Other Income", "Other Income")])
        self.amount = SimpleField("amount", self.data.get("amount", ""), field_type="number")
        self.month = SimpleField("month", self.data.get("month", ""))
        self.year = SimpleField("year", self.data.get("year", ""))
        self.note = SimpleField("note", self.data.get("note", ""), field_type="textarea")


class ExpenseForm(SimpleForm):
    def __init__(self, data=None):
        super().__init__(data)
        predefined = [("Rent", "Rent"), ("Food", "Food"), ("Shopping", "Shopping"), ("Transport", "Transport"), ("Entertainment", "Entertainment"), ("Bills", "Bills"), ("Medical", "Medical"), ("Education", "Education"), ("Insurance", "Insurance"), ("Investment", "Investment"), ("Recharge", "Recharge"), ("Others", "Others")]
        self.category = SimpleField("category", self.data.get("category", "Rent"), field_type="select", choices=predefined)
        self.custom_category = SimpleField("custom_category", self.data.get("custom_category", ""))
        self.amount = SimpleField("amount", self.data.get("amount", ""), field_type="number")
        self.description = SimpleField("description", self.data.get("description", ""), field_type="textarea")
        self.expense_date = SimpleField("expense_date", self.data.get("expense_date", ""), field_type="date")


class FormAdapter:
    def __init__(self, form_obj):
        self.form_obj = form_obj

    @property
    def data(self):
        return self.form_obj.data


class ValidationError(Exception):
    pass


def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return AnonymousUser()
    db = get_db()
    row = db.execute("SELECT id, username, email FROM users WHERE id = ?", (user_id,)).fetchone()
    if row:
        return User(row[0], row[1], row[2])
    session.pop("user_id", None)
    return AnonymousUser()


@app.context_processor
def inject_user():
    return {"current_user": get_current_user()}


def login_required(view_func):
    def wrapped(*args, **kwargs):
        if not get_current_user().is_authenticated:
            flash("Please sign in to continue.", "warning")
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    wrapped.__name__ = view_func.__name__
    return wrapped


def get_db():
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            phone TEXT,
            occupation TEXT,
            monthly_salary REAL DEFAULT 0,
            savings_goal REAL DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS incomes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            income_type TEXT NOT NULL,
            amount REAL NOT NULL,
            month TEXT,
            year TEXT,
            note TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT,
            expense_date TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    db.commit()


def ensure_dataset():
    if DATASET_PATH.exists():
        return
    DATASET_PATH.write_text("income,rent,food,bills,shopping,transport,entertainment,prev_savings,prev_expenses,target_savings\n20000,6000,3500,2400,1600,1400,1000,4000,22000,5000\n50000,15000,9000,6000,4000,3500,2500,10000,45000,8000\n75000,22500,13500,9000,6000,5000,3750,15000,65000,12000\n120000,36000,21600,14400,9600,8400,6000,24000,90000,20000\n", encoding="utf-8")


def format_currency(value):
    return f"₹{float(value):,.2f}"


def calculate_summary(user_id):
    db = get_db()
    profile = db.execute("SELECT monthly_salary, savings_goal FROM profiles WHERE user_id = ?", (user_id,)).fetchone()
    monthly_salary = float(profile[0] or 0) if profile else 0
    savings_goal = float(profile[1] or 0) if profile else 0

    income_rows = db.execute("SELECT amount FROM incomes WHERE user_id = ?", (user_id,)).fetchall()
    expense_rows = db.execute("SELECT amount FROM expenses WHERE user_id = ?", (user_id,)).fetchall()

    total_income = sum(float(row[0]) for row in income_rows)
    total_expenses = sum(float(row[0]) for row in expense_rows)
    remaining_balance = total_income - total_expenses
    savings = remaining_balance
    savings_rate = (savings / total_income * 100) if total_income else 0
    budget_utilization = (total_expenses / total_income * 100) if total_income else 0

    category_totals = {}
    expense_rows_full = db.execute("SELECT category, amount FROM expenses WHERE user_id = ?", (user_id,)).fetchall()
    for row in expense_rows_full:
        category_totals[row[0]] = category_totals.get(row[0], 0) + float(row[1])

    highest_category = max(category_totals.items(), key=lambda item: item[1], default=("None", 0))[0] if category_totals else "None"
    lowest_category = min(category_totals.items(), key=lambda item: item[1], default=("None", 0))[0] if category_totals else "None"

    if monthly_salary:
        total_income = max(total_income, monthly_salary)
        remaining_balance = total_income - total_expenses
        savings = remaining_balance
        savings_rate = (savings / total_income * 100) if total_income else 0
        budget_utilization = (total_expenses / total_income * 100) if total_income else 0

    return {
        "monthly_income": total_income,
        "monthly_expense": total_expenses,
        "remaining_balance": remaining_balance,
        "savings": savings,
        "savings_rate": savings_rate,
        "budget_utilization": budget_utilization,
        "savings_goal": savings_goal,
        "highest_category": highest_category,
        "lowest_category": lowest_category,
        "category_totals": category_totals,
        "monthly_salary": monthly_salary,
    }


def build_ai_recommendations(summary):
    suggestions = []
    if summary["monthly_expense"] > summary["monthly_income"]:
        suggestions.append("Your spending is above your income. Focus on reducing non-essential expenses immediately.")
    if summary["savings_rate"] < 15:
        suggestions.append("Your savings rate is below 15%. Try to hold back at least 15% of income for future goals.")
    if summary["highest_category"] != "None" and summary["category_totals"].get(summary["highest_category"], 0) > summary["monthly_income"] * 0.2:
        suggestions.append(f"{summary['highest_category']} is taking too much of your budget. Consider trimming it this month.")
    if summary["remaining_balance"] < summary["savings_goal"] * 0.5:
        suggestions.append("You are well below your savings goal. Automate a small transfer each payday.")
    if not suggestions:
        suggestions.append("Your budget looks healthy. Keep tracking expenses to maintain your momentum.")
    return suggestions


def build_assistant_reply(prompt, summary, budget_plan):
    text = (prompt or "").strip().lower()
    if not text:
        return "Ask me about your savings, expenses, or budget priorities and I’ll help you plan better."

    if any(word in text for word in ["save", "savings", "goal"]):
        return f"You currently have {format_currency(summary['savings'])} left after expenses, and your savings goal is {format_currency(summary['savings_goal'])}. A good target is to keep at least 15% of income aside each month."

    if any(word in text for word in ["expense", "spend", "budget"]):
        highest = summary["highest_category"]
        if highest == "None":
            return "You have not added enough expenses yet to identify a spending trend. Start with a few expense entries and I’ll guide you from there."
        return f"Your biggest spending category is {highest} at {format_currency(summary['category_totals'].get(highest, 0))}. Consider trimming that area first to improve your balance."

    if any(word in text for word in ["rent", "food", "shopping", "transport", "entertainment", "bills"]):
        category = next((name for name in ["Rent", "Food", "Shopping", "Transport", "Entertainment", "Bills"] if name.lower() in text), "your spending")
        amount = budget_plan.get(category.lower(), 0)
        return f"Your tracked amount for {category} is {format_currency(amount)}. Add more expenses to refine this estimate."

    return "I can help review your savings, major expenses, and budget plan. Try asking about your savings goal or a specific category."


def build_budget_plan(summary):
    category_names = ["Rent", "Food", "Shopping", "Transport", "Entertainment", "Bills"]
    plan = {name.lower(): summary["category_totals"].get(name, 0) for name in category_names}
    plan["savings"] = max(0, summary["monthly_income"] - summary["monthly_expense"])
    plan["predicted_savings"] = max(0, summary["monthly_income"] * 0.18 - (summary["monthly_expense"] * 0.1))
    return plan


def build_chart_data(user_id):
    db = get_db()
    rows = db.execute("SELECT category, amount FROM expenses WHERE user_id = ?", (user_id,)).fetchall()
    categories = {}
    for row in rows:
        categories[row[0]] = categories.get(row[0], 0) + float(row[1])

    bars = []
    max_value = max(categories.values(), default=1)
    for name, value in categories.items():
        width = max(8, int((value / max_value) * 100))
        bars.append(f'<div class="mb-2"><strong>{escape(name)}</strong><div class="progress"><div class="progress-bar" style="width:{width}%">{format_currency(value)}</div></div></div>')
    if not bars:
        bars.append("<p class=""text-muted"">No expense data yet. Add transactions to see your chart.</p>")
    return "".join(bars), "<p class=\"text-muted\">Monthly trend will appear as you record more expenses.</p>"


@app.before_request
def ensure_db_ready():
    init_db()
    ensure_dataset()


@app.route("/")
def index():
    if get_current_user().is_authenticated:
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    form = RegistrationForm(request.form)
    if request.method == "POST" and form.validate():
        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email = ?", (form.email.data.lower(),)).fetchone()
        if existing:
            flash("An account already exists for that email.", "danger")
            return render_template("register.html", form=form)
        user_id = db.execute(
            "INSERT INTO users (username, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (form.username.data.strip(), form.email.data.lower(), generate_password_hash(form.password.data), datetime.now().isoformat()),
        ).lastrowid
        db.execute("INSERT INTO profiles (user_id, created_at) VALUES (?, ?)", (user_id, datetime.now().isoformat()))
        db.commit()
        session["user_id"] = user_id
        flash("Welcome! Your budget planner has been created.", "success")
        return redirect(url_for("dashboard"))
    return render_template("register.html", form=form)


@app.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm(request.form)
    if request.method == "POST" and form.validate():
        db = get_db()
        row = db.execute("SELECT id, username, email, password_hash FROM users WHERE email = ?", (form.email.data.lower(),)).fetchone()
        if row and check_password_hash(row[3], form.password.data):
            session["user_id"] = row[0]
            flash("Logged in successfully.", "success")
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "danger")
    return render_template("login.html", form=form)


@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))


@app.route("/dashboard", methods=["GET", "POST"])
@login_required
def dashboard():
    summary = calculate_summary(get_current_user().id)
    suggestions = build_ai_recommendations(summary)
    budget_plan = build_budget_plan(summary)
    assistant_reply = None

    if request.method == "POST":
        if request.form.get("assistant_prompt"):
            assistant_reply = build_assistant_reply(request.form.get("assistant_prompt"), summary, budget_plan)
        else:
            form = ProfileForm(request.form)
            if form.validate():
                db = get_db()
                db.execute(
                    "INSERT INTO profiles (user_id, phone, occupation, monthly_salary, savings_goal, created_at) VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET phone=excluded.phone, occupation=excluded.occupation, monthly_salary=excluded.monthly_salary, savings_goal=excluded.savings_goal",
                    (get_current_user().id, form.phone.data or "", form.occupation.data or "", float(form.monthly_salary.data or 0), float(form.savings_goal.data or 0), datetime.now().isoformat()),
                )
                db.commit()
                flash("Profile updated successfully.", "success")
                return redirect(url_for("dashboard"))

    profile = get_db().execute("SELECT phone, occupation, monthly_salary, savings_goal FROM profiles WHERE user_id = ?", (get_current_user().id,)).fetchone()
    form = ProfileForm(data={"phone": profile[0] if profile else "", "occupation": profile[1] if profile else "", "monthly_salary": profile[2] if profile else 0, "savings_goal": profile[3] if profile else 0})
    return render_template("dashboard.html", summary=summary, suggestions=suggestions, budget_plan=budget_plan, form=form, assistant_reply=assistant_reply)


@app.route("/budget", methods=["GET", "POST"])
@login_required
def budget():
    income_form = IncomeForm(request.form)
    expense_form = ExpenseForm(request.form)

    if request.method == "POST":
        if "income_submit" in request.form:
            if income_form.validate():
                db = get_db()
                db.execute(
                    "INSERT INTO incomes (user_id, income_type, amount, month, year, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (get_current_user().id, income_form.income_type.data, float(income_form.amount.data), income_form.month.data or datetime.now().strftime("%B"), income_form.year.data or str(datetime.now().year), income_form.note.data or "", datetime.now().isoformat()),
                )
                db.commit()
                flash("Income added successfully.", "success")
                return redirect(url_for("budget"))
        if "expense_submit" in request.form:
            if expense_form.validate():
                chosen_category = request.form.get("category", "")
                custom_category = (request.form.get("custom_category") or "").strip()
                category_name = custom_category if custom_category else chosen_category
                if not category_name:
                    category_name = "Others"
                db = get_db()
                db.execute(
                    "INSERT INTO expenses (user_id, category, amount, description, expense_date, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (get_current_user().id, category_name, float(expense_form.amount.data), expense_form.description.data or "", expense_form.expense_date.data or datetime.now().date().isoformat(), datetime.now().isoformat()),
                )
                db.commit()
                flash(f"Expense recorded under {category_name}.", "success")
                return redirect(url_for("budget"))

    db = get_db()
    incomes = db.execute("SELECT income_type, amount, month, year, note, created_at FROM incomes WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (get_current_user().id,)).fetchall()
    expenses = db.execute("SELECT category, amount, description, expense_date, created_at FROM expenses WHERE user_id = ? ORDER BY created_at DESC LIMIT 10", (get_current_user().id,)).fetchall()
    summary = calculate_summary(get_current_user().id)
    return render_template("budget.html", income_form=income_form, expense_form=expense_form, incomes=incomes, expenses=expenses, summary=summary)


@app.route("/reports")
@login_required
def reports():
    summary = calculate_summary(get_current_user().id)
    pie_html, line_html = build_chart_data(get_current_user().id)
    return render_template("reports.html", summary=summary, pie_chart=pie_html, line_chart=line_html)


@app.route("/export/excel")
@login_required
def export_excel():
    summary = calculate_summary(get_current_user().id)
    # Create a real Excel file using openpyxl
    try:
        from openpyxl import Workbook
    except Exception:
        # Fallback: create a CSV if openpyxl is not available
        content = "Metric,Value\nMonthly Income," + str(summary["monthly_income"]) + "\nMonthly Expense," + str(summary["monthly_expense"]) + "\nRemaining Balance," + str(summary["remaining_balance"]) + "\nSavings," + str(summary["savings"]) + "\nSavings Goal," + str(summary["savings_goal"]) + "\n"
        file_path = EXPORTS_DIR / f"budget_report_{get_current_user().id}.csv"
        file_path.write_text(content, encoding="utf-8")
        return send_file(file_path, as_attachment=True, download_name="budget_report.csv", mimetype="text/csv")

    wb = Workbook()
    ws = wb.active
    ws.title = "Budget Report"
    rows = [
        ("Metric", "Value"),
        ("Monthly Income", summary["monthly_income"]),
        ("Monthly Expense", summary["monthly_expense"]),
        ("Remaining Balance", summary["remaining_balance"]),
        ("Savings", summary["savings"]),
        ("Savings Goal", summary["savings_goal"]),
    ]
    for r in rows:
        ws.append(r)

    file_path = EXPORTS_DIR / f"budget_report_{get_current_user().id}.xlsx"
    wb.save(file_path)
    return send_file(file_path, as_attachment=True, download_name="budget_report.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/export/pdf")
@login_required
def export_pdf():
    summary = calculate_summary(get_current_user().id)
    lines = [
        "AI Budget Planning Report",
        "",
        f"User: {get_current_user().username}",
        "",
        "Metric | Value",
        f"Monthly Income | {format_currency(summary['monthly_income'])}",
        f"Monthly Expense | {format_currency(summary['monthly_expense'])}",
        f"Remaining Balance | {format_currency(summary['remaining_balance'])}",
        f"Savings | {format_currency(summary['savings'])}",
        f"Savings Goal | {format_currency(summary['savings_goal'])}",
    ]

    try:
        # Use reportlab to generate a simple PDF
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas

        file_path = EXPORTS_DIR / f"budget_report_{get_current_user().id}.pdf"
        c = canvas.Canvas(str(file_path), pagesize=letter)
        x = 72
        y = 750
        for line in lines:
            c.drawString(x, y, line)
            y -= 16
            if y < 72:
                c.showPage()
                y = 750
        c.save()
        return send_file(file_path, as_attachment=True, download_name="budget_report.pdf", mimetype="application/pdf")
    except Exception:
        # Fallback: send plain text PDF-like file if reportlab missing
        content = "\n".join(lines)
        file_path = EXPORTS_DIR / f"budget_report_{get_current_user().id}.txt"
        file_path.write_text(content, encoding="utf-8")
        return send_file(file_path, as_attachment=True, download_name="budget_report.txt", mimetype="text/plain")


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
