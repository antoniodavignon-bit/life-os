"""
Life OS — Profit Tracker
=========================
Track daily income entries, view running totals,
and surface weekly/monthly summaries.

Usage:
    python profit_tracker.py

Commands:
    add <amount>     Add a profit entry
    report           View current total
    weekly           View this week's entries
    reset            Reset the tracker
"""

from datetime import datetime


class ProfitTracker:
    """Tracks profit entries with timestamps."""

    def __init__(self):
        self.entries: list[dict] = []
        self.total_profit: float = 0.0

    def add_profit(self, amount: float, note: str = "") -> None:
        """Log a new income entry."""
        entry = {
            "amount": amount,
            "note": note,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M"),
        }
        self.entries.append(entry)
        self.total_profit += amount
        print(f"✅ Logged: ${amount:.2f} — {note or 'No note'}")

    def report(self) -> str:
        """Return a summary of total profit."""
        return f"\n💰 Total Profit Logged: ${self.total_profit:.2f}\n"

    def weekly_summary(self) -> None:
        """Print all entries for context (full log)."""
        if not self.entries:
            print("No entries logged yet.")
            return

        print("\n" + "=" * 40)
        print("     📊 PROFIT LOG — ALL ENTRIES")
        print("=" * 40)
        for entry in self.entries:
            print(f"  {entry['date']} {entry['time']} | ${entry['amount']:.2f} | {entry['note'] or '—'}")
        print("=" * 40)
        print(self.report())

    def reset(self) -> None:
        """Clear all entries and reset total."""
        self.entries = []
        self.total_profit = 0.0
        print("🔄 Profit tracker has been reset.")


if __name__ == "__main__":
    tracker = ProfitTracker()

    # ✏️ Add your real entries here, or connect to a data source
    tracker.add_profit(250.00, "Product sale — Gumroad")
    tracker.add_profit(100.00, "Consulting session")
    tracker.add_profit(19.00, "Life OS sale")

    tracker.weekly_summary()
