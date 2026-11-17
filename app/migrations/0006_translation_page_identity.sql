-- Preserve cached translations while separating identical text on different
-- physical pages: the surrounding scientific context may differ.
UPDATE reader_translations SET quote_hash=CAST(page AS TEXT)||':'||quote_hash
WHERE instr(quote_hash,':')=0;
