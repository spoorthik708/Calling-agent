"use client";

import React, { useState, useEffect } from "react";
import { Navigation } from "@/components/Navigation";
import {
  Users,
  Plus,
  Upload,
  Search,
  Filter,
  RefreshCw,
  X,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Tag,
  Phone,
  Mail,
  UserCheck,
  UserX,
  FileSpreadsheet,
  Trash2,
  Edit2,
  FolderPlus,
} from "lucide-react";

interface Contact {
  id: string;
  tenant_id: string;
  name: string;
  phone_number: string;
  email?: string;
  tags: string[];
  consent_status: string;
  opted_out_at?: string;
  created_at: string;
}

interface ContactList {
  id: string;
  tenant_id: string;
  name: string;
  description?: string;
  contact_count: number;
  created_at: string;
}

interface CSVPreviewResult {
  total_rows: number;
  accepted_count: number;
  rejected_count: number;
  duplicate_count: number;
  sample_accepted: Array<{ name: string; phone_number: string; email?: string; tags: string[] }>;
  rejected_rows: Array<{ row_index: number; raw_phone: string; reason: string }>;
}

export default function ContactsPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [contactLists, setContactLists] = useState<ContactList[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedListId, setSelectedListId] = useState<string>("all");
  const [consentFilter, setConsentFilter] = useState<string>("all");

  // Modals
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [showImportModal, setShowImportModal] = useState<boolean>(false);
  const [showListModal, setShowListModal] = useState<boolean>(false);
  const [editingContact, setEditingContact] = useState<Contact | null>(null);

  // Form States
  const [contactForm, setContactForm] = useState({
    name: "",
    phone_number: "",
    email: "",
    tags_input: "",
    consent_status: "opted_in",
  });

  const [listForm, setListForm] = useState({
    name: "",
    description: "",
  });

  // CSV State
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvPreview, setCsvPreview] = useState<CSVPreviewResult | null>(null);
  const [targetListName, setTargetListName] = useState<string>("");
  const [previewLoading, setPreviewLoading] = useState<boolean>(false);

  const fetchContacts = async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams();
      if (searchQuery) params.append("search", searchQuery);
      if (selectedListId !== "all") params.append("list_id", selectedListId);
      if (consentFilter !== "all") params.append("consent_status", consentFilter);

      const res = await fetch(`/api/v1/contacts?${params.toString()}`);
      if (!res.ok) throw new Error(`Failed to load contacts (${res.status})`);
      const data = await res.json();
      setContacts(data);
    } catch (err: any) {
      setError(err.message || "Error loading contacts.");
    } finally {
      setLoading(false);
    }
  };

  const fetchContactLists = async () => {
    try {
      const res = await fetch("/api/v1/contacts/lists");
      if (res.ok) {
        const data = await res.json();
        setContactLists(data);
      }
    } catch (err) {}
  };

  useEffect(() => {
    fetchContacts();
    fetchContactLists();
  }, [selectedListId, consentFilter]);

  const handleCreateOrUpdateContact = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    const tags = contactForm.tags_input
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    const payload = {
      name: contactForm.name,
      phone_number: contactForm.phone_number,
      email: contactForm.email || null,
      tags: tags,
      consent_status: contactForm.consent_status,
    };

    try {
      const url = editingContact ? `/api/v1/contacts/${editingContact.id}` : "/api/v1/contacts";
      const method = editingContact ? "PUT" : "POST";

      const res = await fetch(url, {
        method: method,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to save contact.");
      }

      setShowAddModal(false);
      setEditingContact(null);
      setContactForm({ name: "", phone_number: "", email: "", tags_input: "", consent_status: "opted_in" });
      fetchContacts();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCreateList = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const res = await fetch("/api/v1/contacts/lists", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(listForm),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to create contact list.");
      }

      setShowListModal(false);
      setListForm({ name: "", description: "" });
      fetchContactLists();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleCsvFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setCsvFile(file);
    setPreviewLoading(true);
    setError(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await fetch("/api/v1/contacts/import/preview", {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Failed to parse CSV file.");
      }

      const data = await res.json();
      setCsvPreview(data);
    } catch (err: any) {
      setError(err.message);
      setCsvFile(null);
      setCsvPreview(null);
    } finally {
      setPreviewLoading(false);
    }
  };

  const handleConfirmImport = async () => {
    if (!csvPreview || csvPreview.sample_accepted.length === 0) return;

    try {
      const payload = {
        list_name: targetListName || (csvFile ? csvFile.name.replace(".csv", "") : "CSV Import"),
        contacts: csvPreview.sample_accepted,
        skip_existing: false,
      };

      const res = await fetch("/api/v1/contacts/import/confirm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.detail || "Import confirmation failed.");
      }

      setShowImportModal(false);
      setCsvFile(null);
      setCsvPreview(null);
      setTargetListName("");
      fetchContacts();
      fetchContactLists();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleOptOut = async (contactId: string) => {
    try {
      const res = await fetch(`/api/v1/contacts/${contactId}/opt-out`, { method: "POST" });
      if (!res.ok) throw new Error("Failed to opt out contact.");
      fetchContacts();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const handleDeleteContact = async (contactId: string) => {
    try {
      const res = await fetch(`/api/v1/contacts/${contactId}`, { method: "DELETE" });
      if (!res.ok) throw new Error("Failed to delete contact.");
      fetchContacts();
    } catch (err: any) {
      setError(err.message);
    }
  };

  const getConsentBadge = (statusStr: string) => {
    switch (statusStr.toLowerCase()) {
      case "opted_in":
        return "bg-emerald-500/10 text-emerald-400 border-emerald-500/20";
      case "opted_out":
        return "bg-rose-500/10 text-rose-400 border-rose-500/20";
      case "suppressed":
        return "bg-amber-500/10 text-amber-400 border-amber-500/20";
      default:
        return "bg-slate-800 text-slate-300 border-slate-700";
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navigation />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-6">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-purple-900/20 pb-6">
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-slate-100">Contacts & Target Lists</h1>
            <p className="text-xs text-slate-400 mt-1">
              Multi-tenant contact directory, consent opt-out tracking, saved segments, and bulk CSV imports.
            </p>
          </div>
          <div className="flex items-center space-x-3">
            <button
              onClick={() => setShowListModal(true)}
              className="flex items-center space-x-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-slate-900 text-slate-300 border border-slate-800 hover:bg-slate-800"
            >
              <FolderPlus className="w-3.5 h-3.5" />
              <span>New List</span>
            </button>
            <button
              onClick={() => setShowImportModal(true)}
              className="flex items-center space-x-2 px-3.5 py-2 rounded-xl text-xs font-medium bg-purple-900/20 text-purple-300 border border-purple-500/30 hover:bg-purple-900/40"
            >
              <Upload className="w-3.5 h-3.5" />
              <span>Import CSV</span>
            </button>
            <button
              onClick={() => {
                setEditingContact(null);
                setContactForm({ name: "", phone_number: "", email: "", tags_input: "", consent_status: "opted_in" });
                setShowAddModal(true);
              }}
              className="flex items-center space-x-2 px-4 py-2 rounded-xl text-xs font-medium bg-purple-600 text-white shadow-lg shadow-purple-500/20 hover:bg-purple-500"
            >
              <Plus className="w-4 h-4" />
              <span>Add Contact</span>
            </button>
          </div>
        </div>

        {/* Error Banner */}
        {error && (
          <div className="p-4 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center space-x-3 text-xs text-rose-300">
            <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Saved Contact Lists Pills */}
        <div className="flex items-center space-x-2 overflow-x-auto pb-2">
          <button
            onClick={() => setSelectedListId("all")}
            className={`px-3 py-1.5 rounded-xl text-xs font-mono transition duration-150 flex items-center space-x-2 ${
              selectedListId === "all"
                ? "bg-purple-600/20 text-purple-300 border border-purple-500/40"
                : "bg-slate-900/60 text-slate-400 border border-slate-800 hover:text-slate-200"
            }`}
          >
            <span>All Contacts</span>
          </button>
          {contactLists.map((lst) => (
            <button
              key={lst.id}
              onClick={() => setSelectedListId(lst.id)}
              className={`px-3 py-1.5 rounded-xl text-xs font-mono transition duration-150 flex items-center space-x-2 ${
                selectedListId === lst.id
                  ? "bg-purple-600/20 text-purple-300 border border-purple-500/40"
                  : "bg-slate-900/60 text-slate-400 border border-slate-800 hover:text-slate-200"
              }`}
            >
              <span>{lst.name}</span>
              <span className="px-1.5 py-0.2 rounded-full bg-slate-800 text-[10px] text-slate-400">
                {lst.contact_count}
              </span>
            </button>
          ))}
        </div>

        {/* Search & Filters */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="relative sm:col-span-2">
            <Search className="w-4 h-4 absolute left-3 top-3 text-slate-500" />
            <input
              type="text"
              placeholder="Search name, phone (+1...), or email..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && fetchContacts()}
              className="w-full pl-9 pr-4 py-2.5 rounded-xl bg-slate-900/80 border border-slate-800 text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-purple-500/50"
            />
          </div>

          <div className="flex items-center space-x-2 bg-slate-900/80 border border-slate-800 rounded-xl px-3 py-2">
            <Filter className="w-4 h-4 text-slate-500" />
            <select
              value={consentFilter}
              onChange={(e) => setConsentFilter(e.target.value)}
              className="bg-transparent text-xs text-slate-200 focus:outline-none w-full"
            >
              <option value="all" className="bg-slate-900">All Consent Statuses</option>
              <option value="opted_in" className="bg-slate-900">Opted In</option>
              <option value="opted_out" className="bg-slate-900">Opted Out</option>
              <option value="suppressed" className="bg-slate-900">Suppressed</option>
            </select>
          </div>
        </div>

        {/* Contacts Table */}
        <div className="rounded-2xl bg-slate-900/60 border border-purple-900/20 backdrop-blur-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs text-slate-300">
              <thead className="bg-slate-900/90 text-slate-400 uppercase font-mono text-[10px] tracking-wider border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Contact Profile</th>
                  <th className="px-6 py-4">Phone Number</th>
                  <th className="px-6 py-4">Consent Status</th>
                  <th className="px-6 py-4">Tags</th>
                  <th className="px-6 py-4">Added Date</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {loading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <tr key={i} className="animate-pulse">
                      <td className="px-6 py-4"><div className="h-4 w-32 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-28 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-16 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-20 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4"><div className="h-4 w-20 bg-slate-800 rounded-md" /></td>
                      <td className="px-6 py-4 text-right"><div className="h-4 w-16 bg-slate-800 rounded-md ml-auto" /></td>
                    </tr>
                  ))
                ) : contacts.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-6 py-12 text-center text-slate-500">
                      <Users className="w-8 h-8 mx-auto mb-2 text-slate-600" />
                      <p>No contacts found. Add contacts or import a CSV file.</p>
                    </td>
                  </tr>
                ) : (
                  contacts.map((c) => (
                    <tr key={c.id} className="hover:bg-slate-800/40 transition duration-150">
                      <td className="px-6 py-4 font-medium text-slate-100">
                        <div>{c.name || "—"}</div>
                        {c.email && <div className="text-[11px] text-slate-500 font-mono">{c.email}</div>}
                      </td>
                      <td className="px-6 py-4 font-mono text-slate-200">
                        {c.phone_number}
                      </td>
                      <td className="px-6 py-4">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-[10px] font-medium border ${getConsentBadge(c.consent_status)}`}>
                          {c.consent_status}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap gap-1">
                          {c.tags && c.tags.length > 0 ? (
                            c.tags.map((t, idx) => (
                              <span key={idx} className="px-2 py-0.5 rounded bg-slate-800 text-slate-400 text-[10px]">
                                {t}
                              </span>
                            ))
                          ) : (
                            <span className="text-slate-600 text-[10px]">—</span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-slate-400">
                        {new Date(c.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-4 text-right space-x-2">
                        {c.consent_status !== "opted_out" && (
                          <button
                            onClick={() => handleOptOut(c.id)}
                            className="px-2.5 py-1 rounded-lg bg-rose-500/10 text-rose-300 border border-rose-500/20 hover:bg-rose-500/20 text-[11px]"
                            title="Set Opt-Out status"
                          >
                            Opt Out
                          </button>
                        )}
                        <button
                          onClick={() => handleDeleteContact(c.id)}
                          className="px-2 py-1 rounded-lg bg-slate-800 text-slate-400 hover:text-rose-400"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Add / Edit Contact Modal */}
        {showAddModal && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <form
              onSubmit={handleCreateOrUpdateContact}
              className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-md w-full p-6 space-y-4 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-semibold text-slate-100">
                  {editingContact ? "Edit Contact Profile" : "Add New Contact"}
                </h3>
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Full Name</label>
                <input
                  type="text"
                  placeholder="e.g. Jane Doe"
                  value={contactForm.name}
                  onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Phone Number (E.164 format)</label>
                <input
                  type="text"
                  required
                  placeholder="+15550199821"
                  value={contactForm.phone_number}
                  onChange={(e) => setContactForm({ ...contactForm, phone_number: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 font-mono focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Email Address (Optional)</label>
                <input
                  type="email"
                  placeholder="jane@example.com"
                  value={contactForm.email}
                  onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Tags (Comma-separated)</label>
                <input
                  type="text"
                  placeholder="Lead, VIP, Q4Campaign"
                  value={contactForm.tags_input}
                  onChange={(e) => setContactForm({ ...contactForm, tags_input: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-medium hover:bg-purple-500"
                >
                  Save Contact
                </button>
              </div>
            </form>
          </div>
        )}

        {/* Create List Modal */}
        {showListModal && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <form
              onSubmit={handleCreateList}
              className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-sm w-full p-6 space-y-4 shadow-2xl"
            >
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <h3 className="text-base font-semibold text-slate-100">Create Contact List Segment</h3>
                <button
                  type="button"
                  onClick={() => setShowListModal(false)}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">List Name</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Q4 Inbound Leads"
                  value={listForm.name}
                  onChange={(e) => setListForm({ ...listForm, name: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div>
                <label className="block text-xs font-medium text-slate-300 mb-1">Description (Optional)</label>
                <input
                  type="text"
                  placeholder="Leads imported from web form"
                  value={listForm.description}
                  onChange={(e) => setListForm({ ...listForm, description: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                />
              </div>

              <div className="flex justify-end space-x-3 pt-2">
                <button
                  type="button"
                  onClick={() => setShowListModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs hover:bg-slate-700"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-medium hover:bg-purple-500"
                >
                  Create List
                </button>
              </div>
            </form>
          </div>
        )}

        {/* CSV Import Modal */}
        {showImportModal && (
          <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
            <div className="bg-slate-900 border border-purple-900/40 rounded-2xl max-w-xl w-full p-6 space-y-4 shadow-2xl">
              <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                <div className="flex items-center space-x-2">
                  <FileSpreadsheet className="w-5 h-5 text-purple-400" />
                  <h3 className="text-base font-semibold text-slate-100">Import Contacts via CSV</h3>
                </div>
                <button
                  onClick={() => {
                    setShowImportModal(false);
                    setCsvFile(null);
                    setCsvPreview(null);
                  }}
                  className="text-slate-400 hover:text-slate-200"
                >
                  <X className="w-5 h-5" />
                </button>
              </div>

              {/* File Upload Box */}
              {!csvPreview ? (
                <div className="border-2 border-dashed border-slate-800 hover:border-purple-500/50 rounded-2xl p-8 text-center space-y-3 transition duration-150">
                  <Upload className="w-8 h-8 mx-auto text-purple-400" />
                  <div className="text-xs text-slate-300">
                    <label className="cursor-pointer text-purple-400 font-semibold hover:underline">
                      Select CSV File
                      <input
                        type="file"
                        accept=".csv,.txt"
                        onChange={handleCsvFileSelect}
                        className="hidden"
                      />
                    </label>{" "}
                    or drag and drop here
                  </div>
                  <p className="text-[11px] text-slate-500">
                    CSV headers supported: Name, Phone, Email, Tags. Phone numbers will be normalized to E.164 format.
                  </p>
                </div>
              ) : (
                <div className="space-y-4">
                  {/* Summary Bar */}
                  <div className="grid grid-cols-3 gap-3 font-mono text-xs text-center">
                    <div className="p-3 rounded-xl bg-slate-950 border border-slate-800">
                      <span className="text-slate-400 block text-[10px]">Total Rows</span>
                      <span className="text-slate-100 font-bold text-base">{csvPreview.total_rows}</span>
                    </div>
                    <div className="p-3 rounded-xl bg-slate-950 border border-emerald-500/30">
                      <span className="text-emerald-400 block text-[10px]">Accepted</span>
                      <span className="text-emerald-300 font-bold text-base">{csvPreview.accepted_count}</span>
                    </div>
                    <div className="p-3 rounded-xl bg-slate-950 border border-rose-500/30">
                      <span className="text-rose-400 block text-[10px]">Rejected</span>
                      <span className="text-rose-300 font-bold text-base">{csvPreview.rejected_count}</span>
                    </div>
                  </div>

                  {/* Target List Name Input */}
                  <div>
                    <label className="block text-xs font-medium text-slate-300 mb-1">
                      Target Contact List Segment Name
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. October Lead Import"
                      value={targetListName}
                      onChange={(e) => setTargetListName(e.target.value)}
                      className="w-full px-3 py-2 rounded-xl bg-slate-950 border border-slate-800 text-xs text-slate-200 focus:outline-none focus:border-purple-500"
                    />
                  </div>

                  {/* Sample Accepted Preview */}
                  <div className="space-y-2">
                    <span className="text-xs text-slate-400 font-semibold block">Accepted Rows Preview</span>
                    <div className="max-h-36 overflow-y-auto rounded-xl border border-slate-800 bg-slate-950 p-2 space-y-1 text-[11px] font-mono">
                      {csvPreview.sample_accepted.map((row, idx) => (
                        <div key={idx} className="flex justify-between border-b border-slate-900 pb-1">
                          <span className="text-slate-200">{row.name || "—"}</span>
                          <span className="text-purple-300">{row.phone_number}</span>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Rejection Warnings if any */}
                  {csvPreview.rejected_rows.length > 0 && (
                    <div className="p-3 rounded-xl bg-rose-500/10 border border-rose-500/20 text-[11px] text-rose-300 space-y-1">
                      <span className="font-semibold block">Rejected Rows Notice:</span>
                      {csvPreview.rejected_rows.slice(0, 3).map((r, i) => (
                        <div key={i}>Row {r.row_index}: {r.reason}</div>
                      ))}
                    </div>
                  )}

                  <div className="flex justify-end space-x-3 pt-2">
                    <button
                      onClick={() => {
                        setCsvFile(null);
                        setCsvPreview(null);
                      }}
                      className="px-4 py-2 rounded-xl bg-slate-800 text-slate-300 text-xs"
                    >
                      Re-select File
                    </button>
                    <button
                      onClick={handleConfirmImport}
                      className="px-4 py-2 rounded-xl bg-purple-600 text-white text-xs font-medium hover:bg-purple-500"
                    >
                      Confirm & Import {csvPreview.accepted_count} Contacts
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
