"use client";

import React, { useState, useEffect } from "react";
import { Navigation } from "@/components/Navigation";
import {
  BarChart3,
  PhoneCall,
  CheckCircle2,
  XCircle,
  Clock,
  RefreshCw,
  AlertCircle,
  PhoneIncoming,
  PhoneOutgoing,
  Megaphone,
  TrendingUp,
  Activity,
} from "lucide-react";

interface AnalyticsData {
  total_calls: number;
  inbound_calls: number;
  outbound_calls: number;
  completed_calls: number;
  failed_calls: number;
  busy_calls: number;
  total_duration_seconds: number;
  average_duration_seconds: number;
}

export default function AnalyticsPage() {
  const [analytics, setAnalytics] = useState<AnalyticsData | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAnalytics = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch("/api/v1/telephony/analytics");
      if (!res.ok) {
        throw new Error(`Failed to fetch analytics (${res.status})`);
      }
      const data = await res.json();
      setAnalytics(data);
    } catch (err: any) {
      setError(err.message || "An error occurred while loading analytics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAnalytics();
  }, []);

  const formatDuration = (seconds: number) => {
    if (!seconds || seconds === 0) return "0s";
    const mins = Math.floor(seconds / 60);
    const secs = Math.round(seconds % 60);
    if (mins === 0) return `${secs}s`;
    return `${mins}m ${secs}s`;
  };

  const calculateCompletionRate = () => {
    if (!analytics || analytics.total_calls === 0) return null;
    return Math.round((analytics.completed_calls / analytics.total_calls) * 100);
  };

  const completionRate = calculateCompletionRate();

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navigation />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-purple-900/20 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Telephony Analytics</h1>
            <p className="text-xs text-slate-400 mt-1">
              Real-time telephony performance metrics, call volume breakdown, and completion statistics.
            </p>
          </div>
          <button
            onClick={fetchAnalytics}
            className="self-start md:self-auto flex items-center space-x-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-purple-900/20 text-purple-300 border border-purple-500/30 hover:bg-purple-900/40 transition duration-200"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
            <span>Refresh Data</span>
          </button>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center space-x-3 text-xs text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Analytics Dashboard Grid */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="p-6 rounded-2xl bg-slate-900/40 border border-slate-800 animate-pulse space-y-3">
                <div className="h-4 w-24 bg-slate-800 rounded" />
                <div className="h-8 w-16 bg-slate-800 rounded" />
                <div className="h-3 w-32 bg-slate-800 rounded" />
              </div>
            ))}
          </div>
        ) : analytics ? (
          <>
            {/* Core Metric Cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {/* Card 1: Total Calls */}
              <div className="p-6 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 border border-purple-900/20 backdrop-blur-sm shadow-xl">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Total Call Volume</span>
                  <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
                    <PhoneCall className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <span className="text-3xl font-extrabold tracking-tight text-slate-100">
                    {analytics.total_calls}
                  </span>
                </div>
                <div className="mt-2 flex items-center space-x-3 text-[11px] text-slate-400">
                  <span className="flex items-center text-sky-400">
                    <PhoneIncoming className="w-3 h-3 mr-1" /> {analytics.inbound_calls} Inbound
                  </span>
                  <span>&bull;</span>
                  <span className="flex items-center text-purple-400">
                    <PhoneOutgoing className="w-3 h-3 mr-1" /> {analytics.outbound_calls} Outbound
                  </span>
                </div>
              </div>

              {/* Card 2: Completion Rate */}
              <div className="p-6 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 border border-purple-900/20 backdrop-blur-sm shadow-xl">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Completion Rate</span>
                  <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                    <CheckCircle2 className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <span className="text-3xl font-extrabold tracking-tight text-slate-100">
                    {completionRate !== null ? `${completionRate}%` : "N/A"}
                  </span>
                </div>
                <div className="mt-2 text-[11px] text-slate-400 font-mono">
                  {analytics.total_calls > 0 ? (
                    <span className="text-emerald-400">{analytics.completed_calls} successful sessions</span>
                  ) : (
                    <span className="text-slate-500">No calls executed yet</span>
                  )}
                </div>
              </div>

              {/* Card 3: Failed & Busy Calls */}
              <div className="p-6 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 border border-purple-900/20 backdrop-blur-sm shadow-xl">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Failed / Busy Calls</span>
                  <div className="p-2 rounded-xl bg-rose-500/10 border border-rose-500/20 text-rose-400">
                    <XCircle className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <span className="text-3xl font-extrabold tracking-tight text-slate-100">
                    {analytics.failed_calls + analytics.busy_calls}
                  </span>
                </div>
                <div className="mt-2 flex items-center space-x-3 text-[11px] text-slate-400 font-mono">
                  <span className="text-rose-400">{analytics.failed_calls} Failed</span>
                  <span>&bull;</span>
                  <span className="text-amber-400">{analytics.busy_calls} Busy/Unanswered</span>
                </div>
              </div>

              {/* Card 4: Call Duration */}
              <div className="p-6 rounded-2xl bg-gradient-to-b from-slate-900/80 to-slate-900/40 border border-purple-900/20 backdrop-blur-sm shadow-xl">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-slate-400">Total Call Time</span>
                  <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                    <Clock className="w-4 h-4" />
                  </div>
                </div>
                <div className="mt-3">
                  <span className="text-3xl font-extrabold tracking-tight text-slate-100">
                    {formatDuration(analytics.total_duration_seconds)}
                  </span>
                </div>
                <div className="mt-2 text-[11px] text-slate-400 font-mono">
                  Avg: <span className="text-slate-200">{analytics.average_duration_seconds}s</span> / call
                </div>
              </div>
            </div>

            {/* Detailed Visualizations Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              {/* Call Outcome Distribution Chart */}
              <div className="p-6 rounded-2xl bg-slate-900/60 border border-purple-900/20 backdrop-blur-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">Call Outcome Breakdown</h3>
                    <p className="text-[11px] text-slate-400">Distribution of call session completion states</p>
                  </div>
                  <Activity className="w-4 h-4 text-purple-400" />
                </div>

                {analytics.total_calls === 0 ? (
                  <div className="h-40 flex items-center justify-center text-xs text-slate-500 italic border border-dashed border-slate-800 rounded-xl">
                    No data available. Execute test calls to view distribution.
                  </div>
                ) : (
                  <div className="space-y-4 pt-2">
                    {/* Visual Segment Bar */}
                    <div className="w-full h-4 bg-slate-950 rounded-full overflow-hidden flex">
                      <div
                        className="h-full bg-emerald-500 transition-all duration-500"
                        style={{ width: `${(analytics.completed_calls / analytics.total_calls) * 100}%` }}
                        title="Completed"
                      />
                      <div
                        className="h-full bg-amber-500 transition-all duration-500"
                        style={{ width: `${(analytics.busy_calls / analytics.total_calls) * 100}%` }}
                        title="Busy / No Answer"
                      />
                      <div
                        className="h-full bg-rose-500 transition-all duration-500"
                        style={{ width: `${(analytics.failed_calls / analytics.total_calls) * 100}%` }}
                        title="Failed"
                      />
                    </div>

                    {/* Outcome Legend */}
                    <div className="grid grid-cols-3 gap-2 text-xs font-mono pt-2">
                      <div className="p-3 rounded-xl bg-slate-950 border border-emerald-500/20">
                        <span className="text-emerald-400 font-semibold block">Completed</span>
                        <span className="text-slate-200 text-base">{analytics.completed_calls}</span>
                        <span className="text-[10px] text-slate-500 block">
                          ({Math.round((analytics.completed_calls / analytics.total_calls) * 100)}%)
                        </span>
                      </div>
                      <div className="p-3 rounded-xl bg-slate-950 border border-amber-500/20">
                        <span className="text-amber-400 font-semibold block">Busy / No Ans</span>
                        <span className="text-slate-200 text-base">{analytics.busy_calls}</span>
                        <span className="text-[10px] text-slate-500 block">
                          ({Math.round((analytics.busy_calls / analytics.total_calls) * 100)}%)
                        </span>
                      </div>
                      <div className="p-3 rounded-xl bg-slate-950 border border-rose-500/20">
                        <span className="text-rose-400 font-semibold block">Failed</span>
                        <span className="text-slate-200 text-base">{analytics.failed_calls}</span>
                        <span className="text-[10px] text-slate-500 block">
                          ({Math.round((analytics.failed_calls / analytics.total_calls) * 100)}%)
                        </span>
                      </div>
                    </div>
                  </div>
                )}
              </div>

              {/* Call Traffic & Direction Split */}
              <div className="p-6 rounded-2xl bg-slate-900/60 border border-purple-900/20 backdrop-blur-sm space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-slate-100">Traffic Direction Analysis</h3>
                    <p className="text-[11px] text-slate-400">Inbound customer calls vs Outbound campaign calls</p>
                  </div>
                  <TrendingUp className="w-4 h-4 text-purple-400" />
                </div>

                {analytics.total_calls === 0 ? (
                  <div className="h-40 flex items-center justify-center text-xs text-slate-500 italic border border-dashed border-slate-800 rounded-xl">
                    No call traffic recorded yet.
                  </div>
                ) : (
                  <div className="space-y-4 pt-2">
                    <div className="space-y-2">
                      <div className="flex justify-between text-xs font-mono">
                        <span className="text-sky-400 flex items-center">
                          <PhoneIncoming className="w-3.5 h-3.5 mr-1" /> Inbound Calls
                        </span>
                        <span className="text-slate-200">{analytics.inbound_calls} sessions ({Math.round((analytics.inbound_calls / analytics.total_calls) * 100)}%)</span>
                      </div>
                      <div className="w-full h-2.5 bg-slate-950 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-sky-500 rounded-full"
                          style={{ width: `${(analytics.inbound_calls / analytics.total_calls) * 100}%` }}
                        />
                      </div>
                    </div>

                    <div className="space-y-2 pt-2">
                      <div className="flex justify-between text-xs font-mono">
                        <span className="text-purple-400 flex items-center">
                          <PhoneOutgoing className="w-3.5 h-3.5 mr-1" /> Outbound Calls
                        </span>
                        <span className="text-slate-200">{analytics.outbound_calls} sessions ({Math.round((analytics.outbound_calls / analytics.total_calls) * 100)}%)</span>
                      </div>
                      <div className="w-full h-2.5 bg-slate-950 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-purple-500 rounded-full"
                          style={{ width: `${(analytics.outbound_calls / analytics.total_calls) * 100}%` }}
                        />
                      </div>
                    </div>

                    <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-400 flex items-center justify-between font-mono">
                      <span>Authenticated Tenant Context:</span>
                      <span className="text-slate-300">Enforced by backend</span>
                    </div>
                  </div>
                )}
              </div>
            </div>
          </>
        ) : null}
      </main>
    </div>
  );
}
