const API_BASE_URL = 'https://carverjobs-mono-production.up.railway.app/api/v1';

export class ApiError extends Error {
  constructor(message: string, public status: number, public data: any) {
    super(message);
  }
}

interface ApiRequestOptions extends RequestInit {
  headers?: Record<string, string>;
}

async function apiRequest(endpoint: string, options: ApiRequestOptions = {}): Promise<any> {
  const url = `${API_BASE_URL}${endpoint}`;
  const token = localStorage.getItem('auth_token');
  
  const defaultOptions: ApiRequestOptions = {
    headers: {
      'Content-Type': 'application/json',
      ...(token && { Authorization: `Bearer ${token}` }),
    },
  };

  const mergedOptions: ApiRequestOptions = {
    ...defaultOptions,
    ...options,
    headers: {
      ...defaultOptions.headers,
      ...options.headers,
    },
  };

  try {
    const response = await fetch(url, mergedOptions);
    const data = await response.json();

    if (!response.ok) {
      throw new ApiError(data.message || 'Request failed', response.status, data);
    }

    return data;
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError('Network error', 0, null);
  }
}

interface RegisterData {
  email: string;
  password: string;
  first_name: string;
  last_name: string;
}

interface LoginCredentials {
  email: string;
  password: string;
}

interface JobFilters {
  type?: string;
  location?: string;
  company?: string;
  limit?: number;
  offset?: number;
}

export const api = {
  // Auth endpoints
  async register(userData: RegisterData) {
    return apiRequest('/auth/register', {
      method: 'POST',
      body: JSON.stringify(userData),
    });
  },

  async login(credentials: LoginCredentials) {
    return apiRequest('/auth/login', {
      method: 'POST',
      body: JSON.stringify(credentials),
    });
  },

  async getProfile() {
    return apiRequest('/auth/profile');
  },

  // Job endpoints
  async getJobs(filters: JobFilters = {}) {
    const params = new URLSearchParams();
    
    if (filters.type) params.append('type', filters.type);
    if (filters.location) params.append('location', filters.location);
    if (filters.company) params.append('company', filters.company);
    if (filters.limit) params.append('limit', filters.limit.toString());
    if (filters.offset) params.append('offset', filters.offset.toString());

    const query = params.toString();
    const endpoint = query ? `/jobs?${query}` : '/jobs';
    
    return apiRequest(endpoint);
  },

  async getJobById(id: string) {
    return apiRequest(`/jobs/${id}`);
  },

  // Health check
  async healthCheck() {
    const response = await fetch('https://carverjobs-mono-production.up.railway.app/health');
    return response.json();
  },
}; 