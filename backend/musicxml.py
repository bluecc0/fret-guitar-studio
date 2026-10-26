"""MusicXML -> quarter-note based score. No inferred tempo or invented notes."""
from fractions import Fraction
from io import BytesIO
import math
import re
import zipfile
import xml.etree.ElementTree as ET

MAX_XML = 20 * 1024 * 1024
class ScoreError(ValueError): pass

def xml_root(data):
    if len(data) > MAX_XML: raise ScoreError('MusicXML 文件过大')
    if re.search(br'<!\s*ENTITY', data, re.I) or re.search(br'<!DOCTYPE[^>]*\[', data, re.I): raise ScoreError('不接受内部 DTD 或实体声明')
    data = re.sub(br'<!DOCTYPE[^>]*>', b'', data, flags=re.I)
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc: raise ScoreError('MusicXML 格式无效') from exc
    for el in root.iter(): el.tag = el.tag.split('}')[-1]
    return root

def unpack_xml(data):
    if not data.startswith(b'PK'): return data
    try:
        with zipfile.ZipFile(BytesIO(data)) as z:
            if sum(i.file_size for i in z.infolist()) > MAX_XML: raise ScoreError('MXL 解压后超过大小限制')
            container = xml_root(z.read('META-INF/container.xml'))
            path = container.find('.//rootfile').get('full-path')
            if not path or path.startswith('/') or '..' in path.split('/'): raise ScoreError('MXL 路径无效')
            return z.read(path)
    except (KeyError, AttributeError, zipfile.BadZipFile) as exc: raise ScoreError('MXL 文件无效') from exc

def number(text, default=None):
    try:
        value = float(text)
        return value if math.isfinite(value) else default
    except (ValueError, TypeError): return default

def parse_musicxml(data):
    root = xml_root(unpack_xml(data))
    if root.tag != 'score-partwise': raise ScoreError('目前支持 score-partwise MusicXML，请先转换此文件')
    names = {p.get('id'): p.findtext('part-name', '声部') for p in root.findall('part-list/score-part')}
    title = root.findtext('work/work-title') or root.findtext('movement-title') or '导入曲谱'
    result = {'version': 1, 'title': title, 'source': 'musicxml', 'parts': [], 'warnings': []}
    for part in root.findall('part'):
        pid = part.get('id', 'P1'); events=[]; measures=[]; tempos=[]; harmonies=[]; warnings=[]
        divisions = Fraction(1); beats = 4; beat_type = 4; meter_known=False; offset=Fraction(0); tie_open={}
        for mi, measure in enumerate(part.findall('measure')):
            attrs = measure.find('attributes')
            if attrs is not None:
                div = attrs.findtext('divisions')
                if div:
                    try: divisions=Fraction(div)
                    except ValueError: raise ScoreError('divisions 无效')
                    if divisions <= 0: raise ScoreError('divisions 必须大于零')
                time = attrs.find('time')
                if time is not None:
                    try:
                        beats=sum(int(x) for x in time.findtext('beats','').split('+'));beat_type=int(time.findtext('beat-type',''))
                    except ValueError: raise ScoreError('不支持的复合拍号，请先校正 MusicXML')
                    if beats<=0 or beat_type<=0: raise ScoreError('拍号无效')
                    meter_known=True
                if attrs.find('transpose') is not None: warnings.append(f'第 {mi+1} 小节含移调，当前保留谱面音高，需核对实际音高。')
            cursor=Fraction(0); maximum=Fraction(0); previous=Fraction(0); m_events=[]
            for child in measure:
                tag=child.tag
                if tag in ('backup','forward'):
                    duration=Fraction(child.findtext('duration','0'))/divisions
                    cursor += duration * (-1 if tag=='backup' else 1)
                    if cursor < 0: raise ScoreError('MusicXML backup 超出小节起点')
                    maximum=max(maximum,cursor)
                elif tag=='direction':
                    sound=child.find('sound');bpm=number(sound.get('tempo')) if sound is not None else None
                    metro=child.find('direction-type/metronome')
                    if bpm is None and metro is not None:
                        unit={'whole':4,'half':2,'quarter':1,'eighth':.5,'16th':.25}.get(metro.findtext('beat-unit'))
                        per=number(metro.findtext('per-minute'))
                        if unit and per:
                            dots=len(metro.findall('beat-unit-dot'));bpm=per*unit*(2-2**(-dots))
                    if bpm and bpm>0:
                        shift=Fraction(child.findtext('offset','0'))/divisions
                        tempos.append({'beat':float(offset+cursor+shift),'bpm':bpm})
                    if sound is not None and any(sound.get(a) for a in ('dacapo','dalsegno','tocoda','fine')):
                        warnings.append(f'第 {mi+1} 小节有反复跳转，当前时间轴按谱面顺序，需要人工确认。')
                    if child.find('direction-type/swing') is not None: warnings.append('检测到 swing，需核对节奏解释。')
                elif tag=='note':
                    if child.find('grace') is not None:
                        warnings.append(f'第 {mi+1} 小节含装饰音，尚未纳入判定。');continue
                    is_chord=child.find('chord') is not None
                    onset=previous if is_chord else cursor
                    try: duration=Fraction(child.findtext('duration','0'))/divisions
                    except ValueError: raise ScoreError('音符时值无效')
                    if duration<=0: raise ScoreError('音符缺少有效 duration，无法确定节奏')
                    voice=child.findtext('voice','1');staff=child.findtext('staff','1')
                    pitch=child.find('pitch');midi=None;label='休止'
                    if pitch is not None:
                        step=pitch.findtext('step');octave=number(pitch.findtext('octave'));alter=number(pitch.findtext('alter'),0)
                        if not step or step not in 'CDEFGAB' or octave is None: raise ScoreError('音高无效')
                        midi=12*(octave+1)+{'C':0,'D':2,'E':4,'F':5,'G':7,'A':9,'B':11}[step]+alter
                        label=step+('#' if alter==1 else 'b' if alter==-1 else '')+str(int(octave))
                    elif child.find('rest') is None:
                        warnings.append(f'第 {mi+1} 小节包含无音高音符，需校正。')
                    technical=child.find('notations/technical')
                    string=number(technical.findtext('string')) if technical is not None else None
                    fret=number(technical.findtext('fret')) if technical is not None else None
                    event={'beat':float(offset+onset),'duration':float(duration),'midi':midi,'label':label,'rest':child.find('rest') is not None,'voice':voice,'staff':staff,'measure':mi+1,'string':string,'fret':fret}
                    ties={t.get('type') for t in child.findall('tie')};key=(voice,staff,midi)
                    prev=tie_open.get(key)
                    if 'stop' in ties and prev is not None and abs(prev['beat']+prev['duration']-event['beat'])<1e-6:
                        prev['duration']+=event['duration']
                        if 'start' not in ties: tie_open.pop(key,None)
                    else:
                        events.append(event);m_events.append(event)
                        if 'stop' in ties: warnings.append(f'第 {mi+1} 小节延音线缺少起点，请核对。')
                    if 'start' in ties: tie_open[key]=prev if 'stop' in ties and prev else event
                    if not is_chord: previous=onset;cursor+=duration
                    maximum=max(maximum,onset+duration,cursor)
                elif tag=='barline':
                    if child.find('repeat') is not None or child.find('ending') is not None:
                        warnings.append(f'第 {mi+1} 小节含反复或房子记号：暂按谱面顺序播放，练习前必须核对。')
                elif tag=='harmony':
                    harmonies.append({'beat':float(offset+cursor+Fraction(child.findtext('offset','0'))/divisions),'root':child.findtext('root/root-step'),'alter':number(child.findtext('root/root-alter'),0),'kind':child.findtext('kind'),'text':child.find('kind').get('text') if child.find('kind') is not None else None})
            expected=Fraction(beats*4,beat_type)
            implicit=measure.get('implicit')=='yes'
            if maximum == 0: raise ScoreError(f'第 {mi+1} 小节没有可用的节奏信息')
            if not implicit and maximum != expected and meter_known:
                warnings.append(f'第 {mi+1} 小节实际 {float(maximum):g} 拍，拍号预期 {float(expected):g} 拍，请对照原谱校正。')
            length=maximum if implicit else max(maximum,expected) if meter_known else maximum
            measures.append({'number':mi+1,'printedNumber':measure.get('number',str(mi+1)),'beat':float(offset),'duration':float(length),'numerator':beats if meter_known else None,'denominator':beat_type if meter_known else None,'implicit':implicit})
            offset+=length
        if tie_open: warnings.append('存在未闭合延音线，请核对原谱。')
        if not meter_known: warnings.append('未识别到拍号，请对照原谱补充。')
        if not any(t['beat']==0 for t in tempos): warnings.append('未识别到起始 BPM，需手动填写；不会自动采用默认速度。')
        if not events: continue
        result['parts'].append({'id':pid,'name':names.get(pid,pid),'events':events,'harmonies':harmonies,'measures':measures,'tempos':sorted(tempos,key=lambda t:t['beat']),'durationBeats':float(offset),'warnings':list(dict.fromkeys(warnings))})
    if not result['parts']: raise ScoreError('没有识别到可用音符')
    result['warnings']=['自动识谱结果需要与原谱对照核验，尤其是拍号、时值与多声部。']
    return result
