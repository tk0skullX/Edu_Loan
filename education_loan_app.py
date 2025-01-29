# -*- coding: utf-8 -*-
"""
education_loan_app_with_date_picker.py

Demonstration of a Streamlit data editor that includes a DateColumn for a calendar pick widget.
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import plotly.express as px

def get_annual_rate_for_date(date, df_rate_schedule, default_rate):
    if df_rate_schedule.empty:
        return default_rate
    df_rate_schedule['effective_date'] = pd.to_datetime(df_rate_schedule['effective_date'])
    df_rate_schedule = df_rate_schedule.sort_values('effective_date')
    applicable = df_rate_schedule[df_rate_schedule['effective_date'] <= date]
    if applicable.empty:
        return default_rate
    else:
        return applicable.iloc[-1]['annual_rate']

def separate_disbursements_amortization(
    df_disb,
    df_payments,
    df_rate_schedule,
    default_annual_rate=0.084,
    monthly_emi=25000,
    start_payment_date=datetime(2025,5,1),
    max_months=216,
    simple_years=3
):
    df_disb['disbursement_date'] = pd.to_datetime(df_disb['disbursement_date'])
    df_payments['payment_date']  = pd.to_datetime(df_payments['payment_date'])

    df_disb = df_disb.sort_values('disbursement_date').reset_index(drop=True)
    df_payments = df_payments.sort_values('payment_date').reset_index(drop=True)

    disbursements_list = []
    for i, row in df_disb.iterrows():
        disbursements_list.append({
            'id': i,
            'disbursement_date': row['disbursement_date'],
            'principal_outstanding': row['amount'],
            'accrued_simple_interest': 0.0
        })

    end_date = start_payment_date + pd.DateOffset(months=max_months)
    period_dates = pd.date_range(start=start_payment_date, end=end_date, freq='MS')
    schedule_rows = []

    for period_idx, current_date in enumerate(period_dates, start=1):
        lumpsum_payment = df_payments.loc[df_payments['payment_date'] == current_date, 'amount'].sum()

        total_interest_this_month = 0.0
        disb_interest_list = []
        for disb in disbursements_list:
            if disb['principal_outstanding'] <= 0 and disb['accrued_simple_interest'] <= 0:
                disb_interest_list.append(0.0)
                continue
            annual_rate = get_annual_rate_for_date(current_date, df_rate_schedule, default_annual_rate)
            monthly_rate = annual_rate / 12.0
            simple_phase_end = disb['disbursement_date'] + pd.DateOffset(years=simple_years)

            if current_date < simple_phase_end:
                interest = disb['principal_outstanding'] * monthly_rate
            else:
                interest = disb['principal_outstanding'] * monthly_rate

            total_interest_this_month += interest
            disb_interest_list.append(interest)

        total_payment = monthly_emi + lumpsum_payment

        interest_paid_list = [0.0]*len(disbursements_list)
        principal_paid_list = [0.0]*len(disbursements_list)

        if total_interest_this_month > 0 and total_payment > 0:
            for i2, disb in enumerate(disbursements_list):
                interest_portion = disb_interest_list[i2]
                if interest_portion <= 0:
                    continue
                ratio = interest_portion / total_interest_this_month
                allocated_interest = total_payment * ratio
                interest_paid_list[i2] = min(allocated_interest, interest_portion)
            interest_paid_sum = sum(interest_paid_list)
            total_payment -= interest_paid_sum
        else:
            interest_paid_sum = 0.0

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

        for i2, disb in enumerate(disbursements_list):
            interest_due = disb_interest_list[i2]
            interest_paid = interest_paid_list[i2]
            unpaid_interest = interest_due - interest_paid
            simple_phase_end = disb['disbursement_date'] + pd.DateOffset(years=simple_years)
            in_simple = (current_date < simple_phase_end)

            if in_simple:
                disb['accrued_simple_interest'] += unpaid_interest
            else:
                disb['principal_outstanding'] += unpaid_interest

            disb['principal_outstanding'] -= principal_paid_list[i2]

            if not in_simple and disb['accrued_simple_interest'] > 0:
                disb['principal_outstanding'] += disb['accrued_simple_interest']
                disb['accrued_simple_interest'] = 0.0

        total_principal_out = sum(d['principal_outstanding'] for d in disbursements_list if d['principal_outstanding']>0)
        total_accrued_si = sum(d['accrued_simple_interest'] for d in disbursements_list if d['accrued_simple_interest']>0)

        schedule_rows.append({
            'Period': period_idx,
            'Date': current_date,
            'Interest_This_Month': sum(disb_interest_list),
            'Interest_Paid': sum(interest_paid_list),
            'Principal_Paid': sum(principal_paid_list),
            'Extra_Payment': lumpsum_payment,
            'Ending_Total_Principal': total_principal_out,
            'Ending_Total_Simple_Interest': total_accrued_si
        })

        if total_principal_out < 1e-8 and total_accrued_si < 1e-8:
            break

    df_schedule = pd.DataFrame(schedule_rows)
    return df_schedule, disbursements_list


def main():
    st.title("Education Loan Calculator with Date Picker in the Data Editor")

    # 1. Disbursements with Date Picker
    st.header("Disbursements with a Calendar Widget")
    st.write("Here, 'disbursement_date' is a DateColumn, giving a calendar to choose from.")
    default_disb = pd.DataFrame({
        'disbursement_date': pd.Series([], dtype='object'),  # empty
        'amount': pd.Series([], dtype='float')
    })

    # Use `st.column_config.DateColumn` for a date picker
    df_disb_user = st.experimental_data_editor(
        default_disb,
        num_rows="dynamic",
        use_container_width=True,
        key="disb_ed",
        column_config={
            "disbursement_date": st.column_config.DateColumn(
                "Disbursement Date",
                format="YYYY-MM-DD"
            ),
            "amount": "Amount (Rs.)"
        }
    )

    # 2. Extra Payments (optional)
    st.header("Extra Payments (Optional)")
    default_payments = pd.DataFrame({
        'payment_date': pd.Series([], dtype='object'),
        'amount': pd.Series([], dtype='float')
    })
    df_pay_user = st.experimental_data_editor(
        default_payments,
        num_rows="dynamic",
        use_container_width=True,
        key="pay_ed",
        column_config={
            "payment_date": st.column_config.DateColumn("Payment Date", format="YYYY-MM-DD"),
            "amount": "Lumpsum Amount (Rs.)"
        }
    )

    # 3. Interest Rate Schedule (optional)
    st.header("Interest Rate Schedule (Optional)")
    default_rates = pd.DataFrame({
        'effective_date': pd.Series([], dtype='object'),
        'annual_rate': pd.Series([], dtype='float')
    })
    df_rate_user = st.experimental_data_editor(
        default_rates,
        num_rows="dynamic",
        use_container_width=True,
        key="rate_ed",
        column_config={
            "effective_date": st.column_config.DateColumn("Effective Date", format="YYYY-MM-DD"),
            "annual_rate": "Annual Rate (%)"
        }
    )

    st.header("Parameters")
    user_interest_pct = st.number_input("Default Annual Interest Rate (%)", value=8.4, step=0.1)
    default_rate = user_interest_pct / 100.0

    monthly_emi = st.slider("Monthly EMI", min_value=0, max_value=200000, step=5000, value=25000)
    start_date = st.date_input("Repayment Start Date", value=datetime(2025,5,1))
    max_months = st.number_input("Max Tenure in Months", min_value=12, max_value=480, value=216, step=12)
    simple_years = st.number_input("Simple Interest Period (Years)", min_value=1, max_value=10, value=3)

    if st.button("Calculate Loan Schedule"):
        # Clean data if user left blank rows
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
            start_payment_date=start_date,
            max_months=max_months,
            simple_years=simple_years
        )

        if df_schedule.empty:
            st.warning("No schedule generated. Possibly zero data or zero EMI?")
        else:
            st.subheader("Repayment Schedule")
            st.dataframe(df_schedule)
            total_interest_paid = df_schedule['Interest_Paid'].sum()
            months_taken = df_schedule['Period'].iloc[-1]

            st.write(f"**Total Interest Paid:** {total_interest_paid:,.2f} Rs.")
            st.write(f"**Months Taken to Repay:** {months_taken}")

            fig = px.line(df_schedule, x='Date', y='Ending_Total_Principal', title='Outstanding Principal Over Time')
            st.plotly_chart(fig, use_container_width=True)


if __name__ == "__main__":
    main()
