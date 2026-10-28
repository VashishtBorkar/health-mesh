"""Static research figures for private diagnostic reports."""
from __future__ import annotations

from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np


def plot_diagnostic(directory, plan, records, audit):
    plt.rcParams.update({"font.size":10,"axes.titlesize":11,"axes.labelsize":10,
                         "legend.fontsize":9,"axes.spines.top":False,"axes.spines.right":False})
    colors={"actual":"#26372f","baseline":"#777777","ridge":"#8d2e2c","chronos":"#356b89"}
    figure,axes=plt.subplots(2,2,figsize=(14,8),sharex=True,sharey="row",layout="constrained")
    has_chronos=any(r['model'].startswith('chronos/') for r in records)
    for row,horizon in enumerate([1,3]):
        title="Next-day HRV" if horizon==1 else "Next three-day average HRV"
        task=[r for r in records if r['horizonDays']==horizon]
        observed={r['date']:r['actual'] for r in task}
        dates=sorted(observed)
        actual=[observed[d] if observed[d] is not None else np.nan for d in dates]
        plot_dates=[date.fromisoformat(d) for d in dates]
        simple_names=('training_mean','training_median','persistence','trailing_mean_7','trailing_median_7')
        def baseline_error(name):
            errors=[abs(r['prediction']-r['actual']) for r in task
                    if r['model']==name and r['actual'] is not None and r['prediction'] is not None]
            return float(np.mean(errors)) if errors else float('inf')
        baseline=min(simple_names,key=baseline_error)
        for col,model in enumerate(['ridge/combined','chronos/combined' if has_chronos else 'ridge/history']):
            ax=axes[row,col]
            ax.plot(plot_dates,actual,color=colors['actual'],marker='o',markersize=4,linewidth=1.6,label='Actual')
            for name,color,style,label in [(baseline,colors['baseline'],'--',baseline),
                                            (model,colors['ridge'] if model.startswith('ridge') else colors['chronos'],'-',model)]:
                series={r['date']:r['prediction'] for r in task if r['model']==name}
                ax.plot(plot_dates,[series.get(d) if series.get(d) is not None else np.nan for d in dates],
                        color=color,linestyle=style,linewidth=1.5,label=label)
            for fold in plan['folds'][1:]:
                ax.axvline(date.fromisoformat(fold['start']),color='#cccccc',linewidth=.8)
            ax.set_title(f"{title}: {'regression' if model.startswith('ridge') else 'Chronos'}")
            ax.set_ylabel('HRV (ms)')
            ax.grid(axis='y',alpha=.2)
            ax.legend(loc='upper right')
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=4))
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
        axes[row,0].set_xlabel('First target date')
        axes[row,1].set_xlabel('First target date')
    figure.suptitle('HRV development forecasts — final test period excluded',fontsize=14)
    figure.savefig(directory/'forecast_comparison.png',dpi=150)
    plt.close(figure)

    fig,ax=plt.subplots(figsize=(12,4.5),layout='constrained')
    entries=audit['records']
    dates=[date.fromisoformat(r['date']) for r in entries]
    values=[r['canonicalHRV'] for r in entries]
    ax.plot(dates,values,color=colors['actual'],marker='o',markersize=3,linewidth=1,label='Recorded nightly HRV')
    for i,jump in enumerate(audit['largestJumps']):
        day=date.fromisoformat(jump['date'])
        ax.scatter([day],[jump['actualHRV']],color=colors['ridge'],s=30,zorder=4)
        ax.annotate(day.strftime('%b %d'),(day,jump['actualHRV']),xytext=(5,12 if i%2==0 else -22),
                    textcoords='offset points',fontsize=9)
    ax.margins(y=.2,x=.03)
    ax.set_title('Development HRV: five largest changes between observed readings')
    ax.set_xlabel('Provider-assigned local date')
    ax.set_ylabel('HRV (ms)')
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.grid(axis='y',alpha=.2)
    ax.legend(loc='upper left')
    fig.savefig(directory/'source_jumps.png',dpi=150)
    plt.close(fig)
