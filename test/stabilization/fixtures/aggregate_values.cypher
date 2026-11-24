CREATE NODE TABLE wide(k INT64 PRIMARY KEY, amount INT64, missing INT64);
CREATE NODE TABLE empty_rows(k INT64 PRIMARY KEY);
CREATE (:wide {k: 1, amount: 9223372036854775807});
CREATE (:wide {k: 2, amount: 9223372036854775807});
CREATE (:wide {k: 3, amount: -10});
CREATE (:wide {k: 4});
