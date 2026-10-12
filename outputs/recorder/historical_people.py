"""Public historical identities, never arbitrary names from attendance checks."""
import re
PEOPLE=[
 ('Александр Невский',r'Александр\w*\s+Невск\w*'),('Дмитрий Донской',r'Дмитри\w*\s+Донск\w*'),
 ('Иван Калита',r'Иван\w*\s+Калит\w*'),('Даниил Московский',r'Даниил\w*\s+Московск\w*'),
 ('Иван Грозный',r'Иван\w*\s+Грозн\w*'),('Пётр Великий',r'П[её]тр\w*\s+(?:Перв\w*|Велик\w*|I)\b'),
 ('Екатерина Великая',r'Екатерин\w*\s+(?:Втор\w*|Велик\w*|II)\b'),('Иван III',r'Иван\w*\s+(?:Трет\w*|III)\b'),
 ('Иван IV',r'Иван\w*\s+(?:Четв[её]рт\w*|IV)\b'),('Владимир Святославич',r'Владимир\w*\s+(?:Святославич\w*|Свят\w*|Красн\w*\s+Солнышко)'),
 ('Ярослав Мудрый',r'Ярослав\w*\s+Мудр\w*'),('Владимир Мономах',r'Владимир\w*\s+Мономах\w*'),
 ('Юрий Долгорукий',r'Юри\w*\s+Долгорук\w*'),('Сергий Радонежский',r'Серги\w*\s+Радонежск\w*'),
 ('Андрей Рублёв',r'Андре\w*\s+Ру[бд]л[её]в\w*'),('Феофан Грек',r'(?:Феофан|Феотан|Диафан|Пиатан)\w*\s+Грек\w*'),
 ('Афанасий Никитин',r'Афанаси\w*\s+Никитин\w*'),('Аристотель Фиораванти',r'Аристотел\w*\s+Фиоравант\w*'),
 ('Александр Суворов',r'Александр\w*\s+Суворов\w*'),('Михаил Кутузов',r'Михаил\w*\s+Кутузов\w*'),
 ('Наполеон Бонапарт',r'Наполеон\w*(?:\s+Бонапарт\w*)?'),('Юлий Цезарь',r'Юли\w*\s+Цезар\w*'),
 ('Александр Македонский',r'Александр\w*\s+Македонск\w*'),('Чингисхан',r'Чингис\s*хан\w*'),
 ('Николай II',r'Никола\w*\s+(?:Втор\w*|II)\b'),('Михаил Ломоносов',r'Михаил\w*\s+Ломоносов\w*')]
ROLE=re.compile(r'княз|правител|цар|император|полковод|корол|султан|хан|воевод|художник|икон|живопис|писател|путешествен|архитектор|уч[её]н|правил|сражени|битв|летопис|престол|московск\w*\s+государств',re.I)
PRIVATE=re.compile(r'одногрупп|студент|переклич|присутств|отсутств|подним\w*\s+рук|отмечаю|отвечай|следующий',re.I)

def identified_people(text,context=''):
 if PRIVATE.search(text) or not ROLE.search(text+' '+context):return []
 return [(name,match.group()) for name,pattern in PEOPLE if (match:=re.search(r'\b'+pattern+r'\b',text,re.I))]

def person_query(item):
 query=item.get('image_query')
 return query if query in [name for name,_ in identified_people(item.get('quote',''),item.get('context',''))] else None

def private_name_query(query,context):
 if PRIVATE.search(context):return True
 # Common personal-name queries must resolve to the explicit historical registry.
 return bool(re.match(r'^(?:Даниил|Данил|Даня|Илья|Александр|Алексей|Андрей|Михаил|Иван|Николай|П[её]тр|Екатерина|Мария|Анна|Сергей|Дмитрий)(?:\s|$)',query or '',re.I)) and not identified_people(query,context)
