// Shared types for frontend and backend communication

export interface User {
  id: string;
  email: string;
  firstName: string;
  lastName: string;
  role: string;
  createdAt: string;
  updatedAt: string;
}

export interface CreateUserRequest {
  email: string;
  password: string;
  firstName: string;
  lastName: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  user: User;
}

export interface Job {
  id: string;
  title: string;
  company: string;
  location?: string;
  type?: string;
  vessel?: string;
  duration?: string;
  salary?: string;
  description?: string;
  requirements?: string;
  sourceUrl?: string;
  source: string;
  postedAt?: string;
  scrapedAt: string;
  createdAt: string;
  updatedAt: string;
}

export interface JobFilter {
  type?: string;
  location?: string;
  company?: string;
  limit?: number;
  offset?: number;
}

export interface JobResponse {
  jobs: Job[];
  total: number;
  page: number;
  limit: number;
}

export interface ApiError {
  message: string;
  code?: string;
} 