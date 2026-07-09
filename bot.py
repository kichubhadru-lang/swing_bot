from strategy import run_scanner
from telegram_bot import send_telegram, format_signals
from portfolio import portfolio_monitor, add_signals_to_journal, available_cash, get_open_symbols
from reports import save_reports


def replacement_message(scanner):
    if scanner is None or scanner.empty:
        return '🔍 REPLACEMENT TRADE IDEAS\n\nNo scanner data available.'
    cash = available_cash()
    open_symbols = get_open_symbols()
    replacements = scanner[~scanner['Symbol'].isin(open_symbols)].copy()
    replacements = replacements[replacements['Capital Required'] <= cash]
    replacements = replacements.sort_values(['Score', 'RS %'], ascending=False).head(3)
    msg = f'🔍 REPLACEMENT TRADE IDEAS\n\nAvailable Cash: ₹{cash}\nAlready Holding: {", ".join(open_symbols) if open_symbols else "None"}\n\n'
    if replacements.empty:
        msg += 'No suitable replacement trade found.'
        return msg
    for i, (_, row) in enumerate(replacements.iterrows(), start=1):
        msg += (f"{i}. {row['Symbol']}\nScore: {row['Score']}/100\nEntry: ₹{row['Entry']}\n"
                f"SL: ₹{row['Stop Loss']}\nTarget: ₹{row['Target']}\nQty: {row['Quantity']}\n"
                f"Capital: ₹{round(row['Capital Required'])}\nRS: {row['RS %']}%\n\n")
    return msg


def main():
    scanner, candidates, final = run_scanner()
    print('Stocks analyzed:', 0 if scanner is None else len(scanner))
    print('Candidates:', 0 if candidates is None else len(candidates))
    print('Signals found:', 0 if final is None else len(final))

    send_telegram(format_signals(final))

    if final is not None and not final.empty:
        added = add_signals_to_journal(final)
        print('Trades added to journal:', added)

    send_telegram(portfolio_monitor())
    send_telegram(replacement_message(scanner))
    save_reports(scanner, candidates, final)
    print('Done')


if __name__ == '__main__':
    main()
