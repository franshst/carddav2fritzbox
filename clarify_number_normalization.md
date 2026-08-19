Telephone numbers should be stored intermediate as normalized numbers.
Normalized numbers contain only decimals and a leading + (international access) sign.
A number in the source telephone books may be stored without international access, country code or area code.
To normalize a number:
1. Strip all non-numerics, keep only the leading +
2. If number starts with +, finish, number is normalized
3. If number starts with numeric international access
(code to be fetched from config.ini, 00 in Europe, 09 in US, may be different elsewhere), then replace international access with +, and finish
4. if number starts with 0, replace leading 0 with +  and country code, finish
5. otherwise, add +, country code and area code without leading zero. Finish

A number should be stored shortened into the FritzBox telephone book. To shorten:
1. If country code of the telephone number is not equal to the country code of the telephone book, finish.
2. Else, remove the + and country code, add leading 0. If area code is equal to the area code of the telephone book, remove the area code. Finish.

to compare two telephone numbers, always use the normalized numbers.
