import csv
import sys
from pathlib import Path

def compute_accuracy(sample_path: str = "data/out/validation_sample.csv"):
    p = Path(sample_path)
    if not p.exists():
        print(f"Error: file not found at {sample_path}")
        return

    total_rows = 0
    checked_rows = 0
    
    # Counts for filled pipeline values
    units_filled = 0
    units_correct = 0
    units_unknown_pipeline = 0
    
    contact_filled = 0
    contact_correct = 0
    contact_unknown_pipeline = 0
    
    email_filled = 0
    email_correct = 0
    email_unknown_pipeline = 0

    with open(p, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_rows += 1
            # Row is human checked if any of the manual columns is filled
            m_u = row.get("manual_units_managed", "").strip()
            m_c = row.get("manual_contact_name", "").strip()
            m_e = row.get("manual_contact_email", "").strip()
            u_corr = str(row.get("units_correct", "")).strip().lower()
            c_corr = str(row.get("contact_correct", "")).strip().lower()
            e_corr = str(row.get("email_correct", "")).strip().lower()

            is_checked = any([m_u, m_c, m_e, u_corr, c_corr, e_corr])
            if is_checked:
                checked_rows += 1
                
                # Evaluate units
                pipe_u = row.get("units_managed", "").strip()
                if pipe_u and pipe_u not in ["unknown", "none", ""]:
                    units_filled += 1
                    if u_corr in ["1", "true", "yes", "y"]:
                        units_correct += 1
                else:
                    units_unknown_pipeline += 1
                    
                # Evaluate contact
                pipe_c = row.get("contact_name", "").strip()
                if pipe_c and pipe_c not in ["unknown", "none", ""]:
                    contact_filled += 1
                    if c_corr in ["1", "true", "yes", "y"]:
                        contact_correct += 1
                else:
                    contact_unknown_pipeline += 1

                # Evaluate email
                pipe_e = row.get("contact_email", "").strip()
                if pipe_e and pipe_e not in ["unknown", "none", ""]:
                    email_filled += 1
                    if e_corr in ["1", "true", "yes", "y"]:
                        email_correct += 1
                else:
                    email_unknown_pipeline += 1

    pending_rows = total_rows - checked_rows

    print("================================================================================")
    print("       ACCURACY AUDIT REPORT ON VALIDATION SAMPLE (40 STRATIFIED ROWS)")
    print(f"       Total Sample: {total_rows} rows | Human-Verified: {checked_rows} | Pending: {pending_rows}")
    print("================================================================================")
    
    if checked_rows == 0:
        print("STATUS: All 40 validation rows are currently PENDING manual human review.")
        print("INSTRUCTIONS FOR HUMAN REVIEWER:")
        print("1. Open data/out/validation_sample.csv (or the 'Validation' tab in leads.xlsx).")
        print("2. In the manual columns, verify against the company website / Impressum.")
        print("3. Enter '1' or 'yes' in units_correct, contact_correct, email_correct.")
        print("4. Re-run 'python compute_accuracy.py' to compute your final precision metrics.")
        print("================================================================================")
        return

    # Report metrics strictly over filled values
    u_acc = round(units_correct / units_filled * 100, 1) if units_filled > 0 else 0.0
    u_cov = round(units_filled / checked_rows * 100, 1)
    print(f"1. Units Managed Accuracy:       {units_correct}/{units_filled} ({u_acc}%) [Coverage: {u_cov}%, Unknown: {units_unknown_pipeline}]")

    c_acc = round(contact_correct / contact_filled * 100, 1) if contact_filled > 0 else 0.0
    c_cov = round(contact_filled / checked_rows * 100, 1)
    print(f"2. Decision Maker Precision:     {contact_correct}/{contact_filled} ({c_acc}%) [Coverage: {c_cov}%, Unknown: {contact_unknown_pipeline}]")

    e_acc = round(email_correct / email_filled * 100, 1) if email_filled > 0 else 0.0
    e_cov = round(email_filled / checked_rows * 100, 1)
    print(f"3. Contact Email Accuracy:       {email_correct}/{email_filled} ({e_acc}%) [Coverage: {e_cov}%, Unknown: {email_unknown_pipeline}]")

    print("--------------------------------------------------------------------------------")
    if pending_rows > 0:
        print(f"NOTE: {pending_rows} rows pending verification. Overall metric withheld until complete.")
    else:
        total_filled = units_filled + contact_filled + email_filled
        total_correct = units_correct + contact_correct + email_correct
        overall_acc = round(total_correct / total_filled * 100, 1) if total_filled > 0 else 0.0
        print(f"OVERALL COMBINED ACCURACY:       {total_correct}/{total_filled} ({overall_acc}%)")
    print("================================================================================")

if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else "data/out/validation_sample.csv"
    compute_accuracy(path)
