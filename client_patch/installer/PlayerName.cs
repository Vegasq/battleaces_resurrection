using System;
using System.Globalization;
using System.Text;

// Same account-default policy as transport/player_name.py; test both on fixtures.
internal static class PlayerName {
    internal static string Clean(string input) {
        input = input ?? "";
        input = input.Substring(input.LastIndexOf('\\') + 1);
        int email = input.IndexOf('@'); if (email >= 0) input = input.Substring(0, email);
        var safe = new StringBuilder();
        for (int i = 0; i < input.Length; i++) {
            if (Char.IsSurrogatePair(input, i)) { safe.Append(input[i]); safe.Append(input[++i]); }
            else safe.Append(Char.IsSurrogate(input[i]) ? ' ' : input[i]);
        }
        input = safe.ToString().Normalize(NormalizationForm.FormC);
        var clean = new StringBuilder(); bool space = false;
        for (int i = 0; i < input.Length; i++) {
            int width = Char.IsSurrogatePair(input, i) ? 2 : 1;
            UnicodeCategory category = CharUnicodeInfo.GetUnicodeCategory(input, i);
            bool allowed = Char.IsLetter(input, i) || category == UnicodeCategory.DecimalDigitNumber ||
                category == UnicodeCategory.NonSpacingMark || category == UnicodeCategory.SpacingCombiningMark ||
                category == UnicodeCategory.EnclosingMark || (width == 1 && "._-'()".IndexOf(input[i]) >= 0);
            if (allowed) {
                if (space && clean.Length > 0) clean.Append(' ');
                clean.Append(input, i, width); space = false;
            } else space = true;
            i += width - 1;
        }
        input = clean.ToString().Trim(' ', '.', '_', '-');
        int count = 0, end = 0;
        while (end < input.Length && count < 32) { end += Char.IsSurrogatePair(input, end) ? 2 : 1; count++; }
        input = input.Substring(0, end).TrimEnd();
        return input.Length == 0 ? "Player" : input;
    }

    internal static string Default() {
        try { return Clean(Environment.UserName); }
        catch (Exception) { return "Player"; }
    }
}
