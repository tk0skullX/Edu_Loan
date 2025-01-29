# -*- coding: utf-8 -*-
"""education_loan_app.py
"""
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.express as px

# ---------------------------------------------------------
# A. Helper function to fetch the annual interest rate for a given date
#    based on a user-defined "rate schedule."
# ---------------------------------------------------------
def get_annual_rate_for_date(date, df_rate_schedule, default_rate):
    """
    df_rate_schedule: DataFrame with columns ['effective_date','annual_rate']
       - 'effective_date' indicates from that date onward, a certain rate applies
    default_rate: if no schedule is provided or if date < earliest schedule date
    returns an annual interest rate (decimal), e.g. 0.084 for 8.4%
    """
    if df_rate_schedule.empty:
        return default_rate

    # Ensure date columns are datetime
    df_rate_schedule['effective_date'] = pd.to_datetime(df_rate_schedule['effective_date'])
    df_rate_schedule = df_rate_schedule.sort_values('effective_date')

    # Filter schedule rows where effective_date <= the current date
    applicable = df_rate_schedule[df_rate_schedule['effective_date'] <= date]
    if applicable.empty:
        # If the date is before the first effective_date, return default
        return default_rate
    else:
        # Return the most recent rate that started on or before this date
        latest_row = applicable.iloc[-1]
        return latest_row['annual_rate']

# ---------------------------------------------------------
# B. Core loan calculation function (Separate Disbursements)
# ---------------------------------------------------------
def separate_disbursements_amortization(
    df_disb,               # DataFrame: [disbursement_date, amount]
    df_payments,           # DataFrame: [payment_date, amount]
    df_rate_schedule,      # DataFrame: [effective_date, annual_rate], optional
    default_annual_rate=0.084,  # fallback if no schedule applies, e.g. 0.084
    monthly_emi=25000,           # user-chosen EMI
    start_payment_date=datetime(2025,5,1),
    max_months=216,        # up to 18 years
    simple_years=3         # 3-year simple interest window for each disb
):
    """
    Returns:
      - df_schedule: monthly aggregated schedule (DataFrame)
      - disbursements_list: final state of each disbursement 
    """

    # Ensure correct dtypes
    df_disb['disbursement_date'] = pd.to_datetime(df_disb['disbursement_date'])
    df_payments['payment_date']  = pd.to_datetime(df_payments['payment_date'])

    # Sort data
    df_disb = df_disb.sort_values('disbursement_date').reset_index(drop=True)
    df_payments = df_payments.sort_values('payment_date').reset_index(drop=True)

    # Build a list of disbursements with tracking fields
    disbursements_list = []
    for i, row in df_disb.iterrows():
        disbursements_list.append({
            'id': i,
            'disbursement_date': row['disbursement_date'],
            'principal_outstanding': row['amount'],
            'accrued_simple_interest': 0.0  # interest in simple phase that hasn't been capitalized
        })

    # Create a monthly date range from start_payment_date up to max_months
    end_date = start_payment_date + pd.DateOffset(months=max_months)
    period_dates = pd.date_range(start=start_payment_date, end=end_date, freq='MS')  # Month start

    schedule_rows = []

    for period_idx, current_date in enumerate(period_dates, start=1):
        # 1) Check lumpsum payment on this date
        lumpsum_payment = df_payments.loc[df_payments['payment_date'] == current_date, 'amount'].sum()

        # 2) Calculate interest for each disbursement
        total_interest_this_month = 0.0
        disb_interest_list = []

        for disb in disbursements_list:
            # If fully cleared, skip
            if disb['principal_outstanding'] <= 0 and disb['accrued_simple_interest'] <= 0:
                disb_interest_list.append(0.0)
                continue

            # Fetch the correct annual rate for this month from schedule
            annual_rate = get_annual_rate_for_date(current_date, df_rate_schedule, default_annual_rate)
            monthly_rate = annual_rate / 12.0

            # Determine if still in simple interest window
            simple_phase_end = disb['disbursement_date'] + pd.DateOffset(years=simple_years)
            if current_date < simple_phase_end:
                # Simple interest = principal_outstanding * monthly_rate
                interest = disb['principal_outstanding'] * monthly_rate
            else:
                # Compound interest
                interest = disb['principal_outstanding'] * monthly_rate

            total_interest_this_month += interest
            disb_interest_list.append(interest)

        # 3) The user’s total payment for this month
        total_payment = monthly_emi + lumpsum_payment

        # 4a) Pay interest first (allocated proportionally)
        interest_paid_list = [0.0]*len(disbursements_list)
        principal_paid_list = [0.0]*len(disbursements_list)

        if total_interest_this_month > 0 and total_payment > 0:
            for i2, disb in enumerate(disbursements_list):
                interest_portion = disb_interest_list[i2]
                if interest_portion <= 0:
                    continue
                ratio = interest_portion / total_interest_this_month
                allocated_interest = total_payment * ratio
                # can't pay more than interest_portion
                interest_paid_list[i2] = min(allocated_interest, interest_portion)
            interest_paid_sum = sum(interest_paid_list)
            total_payment -= interest_paid_sum
        else:
            interest_paid_sum = 0.0

        # 4b) Pay principal with leftover
        total_outstanding_principal = sum(d['principal_outstanding'] for d in disbursements_list if d['principal_outstanding']>0)
        if total_payment > 0 and total_outstanding_principal > 0:
            for i2, disb in enumerate(disbursements_list):
                if disb['principal_outstanding'] > 0:
                    fraction = disb['principal_outstanding'] / total_outstanding_principal
                    allocated_principal = total_payment * fraction
                    principal_paid_list[i2] = min(allocated_principal, disb['principal_outstanding'])
            principal_paid_sum = sum(principal_paid_list)
            total_payment -= principal_paid_sum
        else:
            principal_paid_sum = 0.0

        # 5) Update each disbursement
        for i2, disb in enumerate(disbursements_list):
            interest_due = disb_interest_list[i2]
            interest_paid = interest_paid_list[i2]
            unpaid_interest = interest_due - interest_paid

            simple_phase_end = disb['disbursement_date'] + pd.DateOffset(years=simple_years)
            in_simple = (current_date < simple_phase_end)

            if in_simple:
                # Accumulate any unpaid interest in accrued_simple_interest
                disb['accrued_simple_interest'] += unpaid_interest
            else:
                # In compound phase, unpaid interest is capitalized
                disb['principal_outstanding'] += unpaid_interest

            # Subtract principal paid
            disb['principal_outstanding'] -= principal_paid_list[i2]

            # If we've crossed from simple to compound, capitalize any leftover
            if not in_simple and disb['accrued_simple_interest'] > 0:
                disb['principal_outstanding'] += disb['accrued_simple_interest']
                disb['accrued_simple_interest'] = 0.0

        # Summaries for schedule
        total_principal_out = sum(d['principal_outstanding'] for d in disbursements_list if d['principal_outstanding']>0)
        total_accrued_si = sum(d['accrued_simple_interest'] for d in disbursements_list if d['accrued_simple_interest']>0)

        schedule_rows.append({
            'Period': period_idx,
            'Date': current_date,
            'Interest_This_Month': sum(disb_interest_list),
            'Interest_Paid': interest_paid_sum,
            'Principal_Paid': principal_paid_sum,
            'Extra_Payment': lumpsum_payment,
            'Ending_Total_Principal': total_principal_out,
            'Ending_Total_Simple_Interest': total_accrued_si
        })

        # Stop if fully paid
        if total_principal_out < 1e-8 and total_accrued_si < 1e-8:
            break

    df_schedule = pd.DataFrame(schedule_rows)
    return df_schedule, disbursements_list


# ---------------------------------------------------------
# D. Helper to find required EMI for a target payoff months
#    We'll do a simple "binary search" approach to guess EMI.
# ---------------------------------------------------------
def find_required_emi_for_target_months(
    df_disb,
    df_payments,
    df_rate_schedule,
    default_annual_rate,
    start_payment_date,
    max_months,
    simple_years,
    target_months
):
    """
    Returns an approximate EMI needed to finish the loan
    in <= target_months, given lumpsums. 
    We'll search from 0 to 300,000 monthly. 
    """

    left, right = 0, 300000
    best_emi = right
    while left <= right:
        mid = (left + right)//2
        df_sch, final_disbs = separate_disbursements_amortization(
            df_disb=df_disb.copy(),
            df_payments=df_payments.copy(),
            df_rate_schedule=df_rate_schedule.copy(),
            default_annual_rate=default_annual_rate,
            monthly_emi=mid,
            start_payment_date=start_payment_date,
            max_months=max_months,
            simple_years=simple_years
        )
        if df_sch.empty:
            # No schedule or cleared instantly? 
            # Let's treat that as no real solution, push EMI down
            left = mid + 1
            continue
        last_period = df_sch['Period'].iloc[-1]
        final_principal = df_sch['Ending_Total_Principal'].iloc[-1]
        final_simple_int = df_sch['Ending_Total_Simple_Interest'].iloc[-1]

        # If it's fully paid and done <= target_months, 
        # we can try lower EMI to see if there's a smaller feasible
        if final_principal < 1e-8 and final_simple_int < 1e-8 and last_period <= target_months:
            best_emi = mid
            right = mid - 1
        else:
            # Not fully paid, or took more than target_months => need bigger EMI
            left = mid + 1

    return best_emi


# ---------------------------------------------------------
# E. Streamlit App
# ---------------------------------------------------------
def main():
    st.title("Dynamic Education Loan Calculator — Funny Hinglish Edition")
    st.markdown("""
    **Yeh app aapke liye loan ka kissa asaan karta hai!**  
    - Multiple disbursements (alag-alag dates pe paisa liya).  
    - Pehle 3 saal simple interest, uske baad compound (Bhai, yeh compound hai, dhyaan rakhna!).  
    - Floating interest rate (EBLR badalta rahe toh idhar update kar dena).  
    - Lumpsum (Ek dum se paisa fekna) payments aapki marzi!  
    - EMI badhao, kam karo, sab aapke haath mein!  

    *Pro Tip:* "Bhai tere toh lag gaye" agar interest rate bahut zyada ho ya EMI bahut kam rakho, toh loan chalta hi rahega!
    """)

    # Section 1: Disbursements
    st.header("1. Disbursements (Udhar Liya Kab? yyyy-mm-dd)")
    st.write("Fill in your loan disbursement dates and amounts. Sab aapke haath mein, bhai!")
    default_disb = pd.DataFrame({
        'disbursement_date': pd.Series([], dtype='str'),
        'amount': pd.Series([], dtype='float')
    })
    df_disb_user = st.data_editor(
        default_disb,
        num_rows="dynamic",
        use_container_width=True,
        key="disb_ed",
        column_config={
            "disbursement_date": "Disbursement Date",
            "amount": "Amount (Rs.)"
        }
    )

    # Section 2: Extra Payments
    st.header("2. Extra Payments (Optional)")
    st.write("Add lumpsum payments on specific dates if you plan them. (Jaise shaadi pe koi gift mil gaya etc.)")
    default_payments = pd.DataFrame({
        'payment_date': pd.Series([], dtype='str'),
        'amount': pd.Series([], dtype='float')
    })
    df_pay_user = st.data_editor(
        default_payments,
        num_rows="dynamic",
        use_container_width=True,
        key="pay_ed",
        column_config={
            "payment_date": "Payment Date",
            "amount": "Lumpsum Amount (Rs.)"
        }
    )

    # Section 3: Interest Rate Schedule (Optional)
    st.header("3. Interest Rate Schedule (Optional)")
    st.write("Agar bank kabhi interest change kare, toh idhar daal do. Varna default se kaam chala lo.")
    st.write("**Enter as percentage** (e.g. 8.4 = 8.4%), 'effective_date' is jab se yeh rate lagta hai.")
    default_rates = pd.DataFrame({
        'effective_date': pd.Series([], dtype='str'),
        'annual_rate': pd.Series([], dtype='float')  # 8.4 means 8.4%
    })
    df_rate_user = st.data_editor(
        default_rates,
        num_rows="dynamic",
        use_container_width=True,
        key="rate_ed",
        column_config={
            "effective_date": "Effective Date",
            "annual_rate": "Annual Rate (%)"
        }
    )

    # Section 4: Parameters
    st.header("4. Basic Parameters")
    st.markdown("**Default Annual Interest Rate (%)**: Agar koi schedule na ho, toh yeh chalega. Example: 8.4 = 8.4%.")
    user_interest_pct = st.number_input("Default Annual Interest Rate (%)",
                                        min_value=0.0,
                                        max_value=50.0,
                                        value=8.4,
                                        step=0.1,
                                        help="Bhai, 8.4 matlab 8.4%. Mat sochna 0.084.")
    default_rate = user_interest_pct / 100.0  # convert to decimal

    monthly_emi = st.slider("Monthly EMI (Kitna dena chahoge har mahine?)", 
                            min_value=0, max_value=200000, step=5000, value=25000)

    start_date = st.date_input("Repayment Start Date (Kab se dena shuru?)", value=datetime(2025,5,1))
    max_months = st.number_input("Max Tenure in Months (Ek limit daalo)", 
                                 min_value=12, max_value=480, value=216, step=12)
    simple_years = st.number_input("Simple Interest Period (Years from each Disb Date)",
                                   min_value=1, max_value=10, value=3, step=1)

    st.write("---")
    if st.button("Calculate Repayment Schedule"):
        # Convert empty user data to something workable if empty
        if df_disb_user.empty:
            st.warning("Arre bhai, disbursements hi nahi daale! Ab loan kahan se aaya?")
            return
        
        # Clean up data
        # Remove rows that have no date or 0 amount
        df_disb_clean = df_disb_user.dropna(subset=['disbursement_date','amount'])
        df_disb_clean = df_disb_clean[df_disb_clean['amount']>0]

        df_pay_clean = df_pay_user.dropna(subset=['payment_date','amount'])
        df_pay_clean = df_pay_clean[df_pay_clean['amount']>0]

        df_rate_clean = df_rate_user.dropna(subset=['effective_date','annual_rate'])
        df_rate_clean = df_rate_clean[df_rate_clean['annual_rate']>0]

        df_schedule, final_disbs = separate_disbursements_amortization(
            df_disb=df_disb_clean,
            df_payments=df_pay_clean,
            df_rate_schedule=df_rate_clean,
            default_annual_rate=default_rate,
            monthly_emi=monthly_emi,
            start_payment_date=datetime(start_date.year, start_date.month, start_date.day),
            max_months=max_months,
            simple_years=simple_years
        )

        st.subheader("Repayment Schedule")
        if df_schedule.empty:
            st.warning("It appears no payments were computed. Maybe EMI is 0 or data is incomplete? Bhai check kar le!")
        else:
            st.dataframe(df_schedule)
            # Summaries
            total_interest_paid = df_schedule['Interest_Paid'].sum()
            months_taken = df_schedule['Period'].iloc[-1]
            final_principal = df_schedule['Ending_Total_Principal'].iloc[-1]
            final_simple_int = df_schedule['Ending_Total_Simple_Interest'].iloc[-1]

            st.write(f"**Total Interest Paid:** {total_interest_paid:,.2f} Rs.")
            st.write(f"**Months Taken to Repay (if fully repaid):** {months_taken} months")
            st.write(f"**Final Outstanding Principal:** {final_principal:,.2f} Rs.")
            st.write(f"**Final Accrued Simple Interest:** {final_simple_int:,.2f} Rs.")

            if months_taken == max_months and (final_principal>1e-8 or final_simple_int>1e-8):
                st.error("Bhai tere toh lag gaye! Even after the max tenure, loan abhi khatam nahi hua. EMI badha de!")
            elif total_interest_paid > 3e6:
                st.warning("Oho! Interest bahut zyada lag gaya. 'Bhai, EMI badhao ya lumpsum chalao' is my suggestion!")
            else:
                st.info("Payment schedule done. Aage 'Scenario Analysis' dekh le for more calculations!")

            # Chart: Principal Over Time
            fig = px.line(df_schedule, x='Date', y='Ending_Total_Principal',
                          title='Outstanding Principal Over Time')
            st.plotly_chart(fig, use_container_width=True)

            # Chart: Stacked bar of Interest vs. Principal Paid
            df_melted = df_schedule.melt(
                id_vars=['Period','Date'],
                value_vars=['Interest_Paid','Principal_Paid'],
                var_name='PaidType', value_name='Amount'
            )
            fig2 = px.bar(df_melted, x='Date', y='Amount', color='PaidType',
                          barmode='stack', title='Monthly Interest vs. Principal Paid')
            st.plotly_chart(fig2, use_container_width=True)

    st.write("---")
    # Scenario Analysis
    st.header("Scenario Analysis: 'Bhai, agar mujhe X mahine mein khatam karna hai toh EMI kitni honi chahiye?'")
    target_months = st.number_input("Target: Loan should finish within how many months?", 
                                    min_value=1, max_value=600, value=60, step=1)

    if st.button("Find Required EMI"):
        if df_disb_user.empty:
            st.warning("Disbursement data toh daalo pehle, phir scenario check hoga!")
        else:
            df_disb_clean = df_disb_user.dropna(subset=['disbursement_date','amount'])
            df_disb_clean = df_disb_clean[df_disb_clean['amount']>0]

            df_pay_clean = df_pay_user.dropna(subset=['payment_date','amount'])
            df_pay_clean = df_pay_clean[df_pay_clean['amount']>0]

            df_rate_clean = df_rate_user.dropna(subset=['effective_date','annual_rate'])
            df_rate_clean = df_rate_clean[df_rate_clean['annual_rate']>0]

            required_emi = find_required_emi_for_target_months(
                df_disb=df_disb_clean,
                df_payments=df_pay_clean,
                df_rate_schedule=df_rate_clean,
                default_annual_rate=default_rate,
                start_payment_date=datetime(start_date.year, start_date.month, start_date.day),
                max_months=max_months,
                simple_years=simple_years,
                target_months=target_months
            )
            st.success(f"Bhai, agar tu {target_months} mahine mein poora karna chahta hai, to approx EMI ~ Rs. {required_emi:,.2f} chahiye!")

if __name__ == "__main__":
    main()
