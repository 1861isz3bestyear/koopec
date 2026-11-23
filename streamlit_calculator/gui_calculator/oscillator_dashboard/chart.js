'use strict';
// The layout and Canvas rendering follow limit_orders_oscillator. Every point
// comes from the supplied real-data traces; prices never generate depth rates.
const payload = JSON.parse(document.querySelector('#market-data').textContent);
const canvas = document.querySelector('#chart'), ctx = canvas.getContext('2d');
const priceTrace = payload.data.find(trace => trace.name === 'Price');
const margin = payload.data.some(trace => trace.name === 'margin_loan_oscillator_rate');
const rateName = margin ? 'margin_loan_oscillator_rate' : 'limit_order_oscillator_rate';
const rateTrace = payload.data.find(trace => trace.name === rateName);
const [low, high] = margin ? [38, 62] : [30, 70];
const bitgetGrowth = payload.layout.meta?.margin_source === 'bitget_growth';
const growthStep = payload.layout.meta?.growth_period === '24h' ? 3600000 : 86400000;
const rateLabel = bitgetGrowth ? 'Loan growth momentum (14)' : margin ? 'Margin loan rate' : 'Limit order rate';
const observationLabel = bitgetGrowth ? 'Bitget exchange timestamp' : margin ? 'Balances received' : 'Depth observed';
const observations = trace => (trace?.x || []).map((time, index) => ({
  time: Date.parse(time), value: trace.y[index]
})).filter(point => Number.isFinite(point.time) && Number.isFinite(point.value));
const prices = observations(priceTrace), rates = observations(rateTrace);
const [initialStart, initialEnd] = payload.layout.xaxis.range.map(time => Date.parse(time));
let start = initialStart, end = initialEnd;
const symbol = payload.layout.title.text.split(' ')[0];
const names = {BTC:'Bitcoin', ETH:'Ethereum', SOL:'Solana'};
const format = value => value.toLocaleString('en-US', {minimumFractionDigits:2, maximumFractionDigits:2});
const date = time => new Date(time).toLocaleString('en-GB', {day:'numeric', month:'short', ...(end-start <= 2*86400000 ? {hour:'2-digit', minute:'2-digit'} : {}), timeZone:'UTC'});
document.querySelector('#symbol').textContent = `${symbol} / USDT`;
document.querySelector('#chart-title').textContent = names[symbol] || symbol;
document.querySelector('#last-price').textContent = prices.length ? format(prices.at(-1).value) : 'Unavailable';
document.querySelector('#chart-detail').textContent = `1 hour price · recorded ${bitgetGrowth ? 'Bitget loan growth' : margin ? 'loan balances' : 'depth'} · UTC`;
document.querySelector('#data-window').textContent = `${date(start)} – ${date(end)} · UTC`;
let hover = null, geometry = {}, drag = null;
function line(x1,y1,x2,y2,color,dash=[]) {
  ctx.beginPath(); ctx.strokeStyle=color; ctx.lineWidth=1; ctx.setLineDash(dash);
  ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke(); ctx.setLineDash([]);
}
function series(points, x, y, color) {
  ctx.lineCap="round"; ctx.lineJoin="round";
  points.forEach((point,index) => {
    if (index && (!bitgetGrowth || points !== rates || point.time-points[index-1].time===growthStep)) {
      const previous=points[index-1];
      // Split at the actual threshold crossing, so an entire segment does
      // not turn red or green just because its endpoint is extreme.
      const cuts=[0,1];
      if(points===rates && point.value!==previous.value) {
        for(const threshold of [low,high]) {
          const t=(threshold-previous.value)/(point.value-previous.value);
          if(t>0 && t<1) cuts.push(t);
        }
      }
      cuts.sort((a,b)=>a-b);
      for(let i=1;i<cuts.length;i++) {
        const a=cuts[i-1],b=cuts[i];
        const xx=t=>x(previous.time+t*(point.time-previous.time));
        const yy=t=>y(previous.value+t*(point.value-previous.value));
        ctx.beginPath(); ctx.lineWidth=margin?1:2;
        ctx.strokeStyle=color(previous.value+(a+b)/2*(point.value-previous.value));
        ctx.moveTo(xx(a),yy(a)); ctx.lineTo(xx(b),yy(b)); ctx.stroke();
      }
    }
    // A lone recorded book must remain visible without inventing history.
    else if (points.length === 1 || (bitgetGrowth && points === rates)) {
      ctx.beginPath(); ctx.fillStyle=color(point.value);
      ctx.arc(x(point.time),y(point.value),3,0,2*Math.PI); ctx.fill();
    }
  });
}
function thresholdEntries(x,y) {
  let lastLabel=-Infinity;
  rates.forEach((point,index)=>{
    if(!index) return;
    const previous=rates[index-1];
    const long=point.value<=low && previous.value>low;
    const short=point.value>=high && previous.value<high;
    if(!long && !short) return;
    const xx=x(point.time),tip=y(point.value)+(long?7:-7),direction=long?1:-1;
    ctx.fillStyle=long?'#0b5428':'#971d22';
    ctx.beginPath(); ctx.moveTo(xx,tip);
    ctx.lineTo(xx-8,tip+direction*9); ctx.lineTo(xx-3,tip+direction*9);
    ctx.lineTo(xx-3,tip+direction*18); ctx.lineTo(xx+3,tip+direction*18);
    ctx.lineTo(xx+3,tip+direction*9); ctx.lineTo(xx+8,tip+direction*9);
    ctx.closePath(); ctx.fill(); ctx.font='10px sans-serif'; ctx.textAlign='center';
    if(xx-lastLabel>=44) {
      const labelY=tip+(long?31:-23);
      ctx.fillStyle='#ffffff'; ctx.fillRect(xx-20,labelY-11,40,14);
      ctx.fillStyle=long?'#0b5428':'#971d22';
      ctx.fillText(long?'LONG':'SHORT',xx,labelY); lastLabel=xx;
    }
  });
}
function draw() {
  const {width:w,height:h} = canvas.getBoundingClientRect(), ratio = window.devicePixelRatio || 1;
  canvas.width=w*ratio; canvas.height=h*ratio; ctx.scale(ratio,ratio);
  const left=49,right=w-80,top=15,bottom=h-35,split=top+(bottom-top)*.64;
  let min=Infinity,max=-Infinity;
  prices.filter(point => point.time >= start && point.time <= end).forEach(point => {min=Math.min(min,point.value); max=Math.max(max,point.value);});
  if (!Number.isFinite(min)) {min=0; max=1;}
  const pad=Math.max((max-min)*.1,Math.abs(max)*.0001, .001);
  const x=time=>left+(time-start)/(end-start)*(right-left);
  const py=value=>split-25-(value-min+pad)/(max-min+2*pad)*(split-top-35);
  // The reference shares one plot: oscillator 0–240 on the left and
  // an independent price scale on the right, with no panel divider.
  const oy=value=>bottom-value/(margin?100:240)*(margin?bottom-split:bottom-top);
  geometry={left,right}; ctx.font='10px ui-monospace, monospace';
  ctx.fillStyle='#fce7e5'; ctx.fillRect(left,oy(high),right-left,oy(high-8)-oy(high));
  ctx.fillStyle='#e6f4ea'; ctx.fillRect(left,oy(low+8),right-left,oy(low)-oy(low+8));
  for(let i=0;i<=5;i++) {
    const value=min-pad+(1-i/5)*(max-min+2*pad),y=py(value);
    line(left,y,right,y,'#f0f1f5'); ctx.fillStyle='#454c59'; ctx.textAlign='left';
    if(prices.length) ctx.fillText(format(value),right+9,y+3);
  }
  for(let i=0;i<=8;i++) {
    const time=start+i/8*(end-start),xx=x(time);
    line(xx,top,xx,bottom,'#f1f2f6'); ctx.fillStyle='#454c59'; ctx.textAlign='center';
    if(w>600 || i%2===0) ctx.fillText(date(time),xx,bottom+22);
  }
  for(const value of (margin?[0,low,50,high,100]:Array.from({length:13},(_,i)=>i*20))) {
    if(!margin) {
      line(left,oy(value),right,oy(value),'#f3f4f6');
      ctx.fillStyle='#454c59'; ctx.textAlign='right'; ctx.fillText(value.toFixed(2),left-10,oy(value)+3);
      continue;
    }
    line(left,oy(value),right,oy(value),value===low?'#28b463':value===high?'#f05a58':'#e8eaf0',[3,3]);
    ctx.fillStyle='#454c59'; ctx.textAlign='right'; ctx.fillText(value,left-12,oy(value)+3);
  }
  if(!margin) for(const value of [low,50,high]) {
    line(left,oy(value),right,oy(value),value===low?'#28b463':value===high?'#f05a58':'#c7cdd5',[2,2]);
  }
  ctx.save(); ctx.beginPath(); ctx.rect(left,top,right-left,bottom-top); ctx.clip();
  series(prices,x,py,()=> '#9b6700');
  series(rates,x,oy,value=>value>high?'#b42328':value<low?'#14733a':'#738397');
  ctx.fillStyle='#454c59'; ctx.textAlign='left'; ctx.font='9px sans-serif';
  if(margin) ctx.fillText(rateName.toUpperCase(),left+8,split+9);
  if(!margin) thresholdEntries(x,oy);
  ctx.restore();
  ctx.textAlign='center'; ctx.font='12px sans-serif';
  if(!rates.length) ctx.fillText(bitgetGrowth ? 'No warmed-up Bitget growth in this snapshot window' : margin ? 'No recorded loan balances — upload historical balances' : 'No recorded depth — upload historical order books', (left+right)/2,oy(50)-12);
  if(!prices.length) ctx.fillText('No completed price candles', (left+right)/2,(top+split)/2);
  if(prices.length) {
    const latest=prices.at(-1); ctx.fillStyle='#ffbd00'; ctx.fillRect(right,py(latest.value)-10,78,20);
    ctx.fillStyle='#423000'; ctx.textAlign='left'; ctx.font='10px monospace';
    ctx.fillText(format(latest.value),right+5,py(latest.value)+4);
  }
  if(hover!==null) line(x(hover),top,x(hover),bottom,'#959baa',[4,4]);
}
// Show the last observation available at the cursor, never a future point.
function availableAt(points,time) {
  let found=null;
  for(const point of points) {if(point.time>time) break; found=point;}
  return found;
}
canvas.addEventListener('pointermove',event=>{
  const xx=event.clientX-canvas.getBoundingClientRect().left;
  if (drag) {
    const shift=(event.clientX-drag.x)/(geometry.right-geometry.left)*drag.span;
    const next=Math.max(initialStart,Math.min(initialEnd-drag.span,drag.start-shift));
    start=next; end=next+drag.span; clearHover(); return;
  }
  hover=start+Math.max(0,Math.min(1,(xx-geometry.left)/(geometry.right-geometry.left)))*(end-start);
  const price=availableAt(prices,hover),rate=availableAt(rates,hover);
  const tip=document.querySelector('#tooltip'); tip.hidden=false;
  tip.textContent=`${new Date(hover).toISOString().slice(0,16).replace('T',' ')} UTC`+
    `\nPrice  ${price ? format(price.value) : 'No observation'}`+
    `\n${rateLabel}  ${rate ? rate.value.toFixed(1)+'%' : 'No observation'}`+
    (rate ? `\n${observationLabel}  ${new Date(rate.time).toISOString()}` : '');
  draw();
});
function clearHover() {hover=null; document.querySelector('#tooltip').hidden=true; draw();}
function reset() {start=initialStart; end=initialEnd; drag=null; clearHover();}
canvas.addEventListener('pointerleave',clearHover);
canvas.addEventListener('wheel',event=>{
  event.preventDefault();
  const fraction=Math.max(0,Math.min(1,(event.clientX-canvas.getBoundingClientRect().left-geometry.left)/(geometry.right-geometry.left)));
  const span=Math.max(Math.min(3600000,initialEnd-initialStart),Math.min(initialEnd-initialStart,(end-start)*Math.exp(Math.max(-1,Math.min(1,event.deltaY*.001)))));
  const anchor=start+fraction*(end-start);
  start=Math.max(initialStart,Math.min(initialEnd-span,anchor-fraction*span));
  end=start+span; clearHover();
},{passive:false});
canvas.addEventListener('pointerdown',event=>{
  if(event.button!==0) return;
  drag={x:event.clientX,start,span:end-start};
  canvas.setPointerCapture(event.pointerId); clearHover();
});
canvas.addEventListener('pointerup',()=>{drag=null;});
canvas.addEventListener('pointercancel',()=>{drag=null;});
canvas.addEventListener('dblclick',reset);
document.querySelector('#reset').addEventListener('click',reset);
new ResizeObserver(draw).observe(canvas); draw();
